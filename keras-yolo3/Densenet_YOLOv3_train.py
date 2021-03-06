"""
Retrain the YOLO_densenet model for your own dataset.
"""

import numpy as np
import keras.backend as K
from keras.callbacks import LambdaCallback
from keras.layers import Input, Lambda
from keras.models import Model
from keras.optimizers import Adam
from keras.callbacks import TensorBoard, ModelCheckpoint, ReduceLROnPlateau, EarlyStopping

from yolo3.model import preprocess_true_boxes, yolo_body, yolo_loss
from yolo3.model_yolov4 import yolo_bodyV4,yolov4_loss
from yolo3.utils import get_random_data,get_random_data_with_Mosaic
from yolo3.model_densenet import densenet_body
from yolo3.model_se_densenet import se_densenet_body
import sys
from distutils.util import strtobool

modeltype       = sys.argv[11]

def _main():
    #【讀取】annotation位置
    annotation_path = sys.argv[1]#'model_data/train.txt'
    #【讀取】evaluations位置
    val_path        = sys.argv[2]#'model_data/val.txt'
    #【存放】模型位置
    log_dir         = sys.argv[3]#'logs/20200421_Y&D_Adam&1e-4_focalloss&gamma=2.^alpha=.25/'
    #【讀取】classes位置
    classes_path    = sys.argv[4]#'model_data/voc_classes.txt'
    #【讀取】anchors位置
    anchors_path    = sys.argv[5]#'model_data/yolo_anchors.txt'
    #檔案名稱變更用
    load_file       = sys.argv[6]#'500'
    load_pretrained = strtobool(sys.argv[7])# True、False
    #迴圈次數
    epoch           = int(sys.argv[8])#500
    #batch_size大小，每次輸入多少資料
    batch_size      = int(sys.argv[9])#4
    #0.n為用於驗證 其餘用於訓練
    val_split       = float(sys.argv[10])#0.2
    #取得 class_names 類別
    class_names     = get_classes(classes_path)
    #取得 class_names 數量
    num_classes     = len(class_names)
    #取得 anchor
    anchors         = get_anchors(anchors_path)
    mosaic = True
    input_shape     = (416,416) # multiple of 32, hw
    is_tiny_version = len(anchors)==6 # default setting
    model = create_model(input_shape, anchors, num_classes,freeze_body=2,
    load_pretrained=load_pretrained, weights_path=log_dir+'ep'+str(load_file)+'.h5') # make sure you know what you freeze
    logging = TensorBoard(log_dir=log_dir)

    checkpoint = ModelCheckpoint(log_dir +'s'+str(load_file)+'_'+'ep{epoch:03d}-loss{loss:.3f}-val_loss{val_loss:.3f}.h5',
        monitor='val_loss', save_weights_only=True, save_best_only=True, period=3)

    # define your custom callback for prediction
    batch_print_callback = LambdaCallback(
        on_epoch_end=lambda epoch,logs: print(epoch))

    checkpoint = ModelCheckpoint(log_dir +'s'+str(load_file)+'_'+'ep{epoch:03d}-loss{loss:.3f}-val_loss{val_loss:.3f}.h5',
        monitor='val_loss', save_weights_only=True, save_best_only=True, period=3)

    #reduce_lr = ReduceLROnPlateau(monitor='val_loss', factor=0.1, patience=3, verbose=1)
    #early_stopping = EarlyStopping(monitor='val_loss', min_delta=0, patience=10, verbose=1)
    with open(annotation_path) as f:
        lines = f.readlines()

    with open(val_path) as f:
        val_lines = f.readlines()

    np.random.seed(10101)
    np.random.shuffle(lines)
    np.random.shuffle(val_lines)
    np.random.seed(None)

    # num_val = int(len(val_lines))
    # num_train = len(lines)

    num_val = int(len(lines)*val_split)
    num_train = len(lines) - num_val
    #print(len(lines))
    # print(lines[:num_train])
    # print(lines[num_train:])
    if True:
        for i in range(len(model.layers)):
            model.layers[i].trainable = True
        model.compile(optimizer=Adam(lr=1e-4), loss={'yolo_loss': lambda y_true, y_pred: y_pred}) # recompile to apply the change
        # print('Unfreeze all of the layers.')
        model.save(log_dir + 'network.h5')

        #batch_size = 8 # note that more GPU memory is required after unfreezing the body
        print('Train on {} samples, val on {} samples, with batch size {}.'.format(num_train, num_val, batch_size))
        #For Google用
        # model.fit_generator(data_generator_wrapper(lines[:num_train], batch_size, input_shape, anchors, num_classes),
        #     steps_per_epoch=max(1, num_train//batch_size),
        #     validation_data=data_generator_wrapper(val_lines[:len(val_lines)], batch_size, input_shape, anchors, num_classes),
        #     validation_steps=max(1, num_val//batch_size),
        #     epochs=epoch,
        #     initial_epoch=0,
        #     callbacks=[logging, checkpoint])
        #For 測試用
        model.fit_generator(data_generator_wrapper(lines[:num_train], batch_size, input_shape, anchors, num_classes, mosaic=mosaic),
            steps_per_epoch=max(1, num_train//batch_size),
            validation_data=data_generator_wrapper(lines[num_train:], batch_size, input_shape, anchors, num_classes, mosaic=False),
            validation_steps=max(1, num_val//batch_size),
            epochs=epoch,
            initial_epoch=0,
            callbacks=[logging, checkpoint,batch_print_callback])
            #callbacks=[logging, checkpoint, reduce_lr, early_stopping])
        model.save_weights(log_dir + 'ep'+str(int(load_file)+int(epoch))+'.h5')

    # Further training if needed.


def get_classes(classes_path):
    '''loads the classes'''
    with open(classes_path) as f:
        class_names = f.readlines()
    class_names = [c.strip() for c in class_names]
    return class_names

def get_anchors(anchors_path):
    '''loads the anchors from a file'''
    with open(anchors_path) as f:
        anchors = f.readline()
    anchors = [float(x) for x in anchors.split(',')]
    return np.array(anchors).reshape(-1, 2)


def create_model(input_shape, anchors, num_classes, load_pretrained=True, freeze_body=2,
            weights_path='model_data/yolo_weights.h5'):
    '''create the training model'''
    K.clear_session() # get a new session
    image_input = Input(shape=(None, None, 3))
    h, w = input_shape
    num_anchors = len(anchors)

    y_true = [Input(shape=(h//{0:32, 1:16, 2:8}[l], w//{0:32, 1:16, 2:8}[l], \
        num_anchors//3, num_classes+5)) for l in range(3)]
    # print(y_true)
    # return
    if modeltype == "YOLOV3":
        model_body = yolo_body(image_input, num_anchors//3, num_classes)
    if modeltype == "YOLOV4":
        model_body = yolo_bodyV4(image_input, num_anchors//3, num_classes)
    if modeltype == "YOLOV3Densenet":
        model_body = densenet_body(image_input, num_anchors//3, num_classes)
    if modeltype == "YOLOV3SE-Densenet":
        model_body = se_densenet_body(image_input, num_anchors//3, num_classes)
    if modeltype == "SE-YOLOV3":
        model_body = yolo_body(image_input, num_anchors//3, num_classes,"SE-YOLOV3")
    
    print('Create YOLOv3 model with {} anchors and {} classes.'.format(num_anchors, num_classes))
       
    if load_pretrained:
        model_body.load_weights(weights_path, by_name=True, skip_mismatch=True)
        print('Load weights {}.'.format(weights_path))
        if modeltype == "YOLOV3":
            if freeze_body:
                # Do not freeze 3 output layers.
                num = len(model_body.layers)-7
                for i in range(num): model_body.layers[i].trainable = False
                print('Freeze the first {} layers of total {} layers.'.format(num, len(model_body.layers)))
        if modeltype == "SE-YOLOV3":
            if freeze_body:
                # Do not freeze 3 output layers.
                num = len(model_body.layers)-7
                for i in range(num): model_body.layers[i].trainable = False
                print('Freeze the first {} layers of total {} layers.'.format(num, len(model_body.layers)))
        if modeltype == "YOLOV3Densenet":
            if freeze_body in [1, 2]:
                # Freeze darknet53 body or freeze all but 3 output layers.
                num = 424
                for i in range(num): model_body.layers[i].trainable = False
                print('Freeze the first {} layers of total {} layers.'.format(num, len(model_body.layers)))
        if modeltype == "YOLOV3SE-Densenet":
            if freeze_body in [1, 2]:
                # Freeze darknet53 body or freeze all but 3 output layers.
                num = 424
                for i in range(num): model_body.layers[i].trainable = False
                print('Freeze the first {} layers of total {} layers.'.format(num, len(model_body.layers)))
    model_loss = Lambda(yolov4_loss, output_shape=(1,), name='yolo_loss',
        arguments={'anchors': anchors, 'num_classes': num_classes, 'ignore_thresh': 0.5})(
        [*model_body.output, *y_true])
    model = Model([model_body.input, *y_true], model_loss)

    #model.summary()

    return model

def data_generator(annotation_lines, batch_size, input_shape, anchors, num_classes, mosaic=False):
    '''data generator for fit_generator'''
    n = len(annotation_lines)
    i = 0
    flag = True
    while True:
        image_data = []
        box_data = []
        for b in range(batch_size):
            if i==0:
                np.random.shuffle(annotation_lines)
            if mosaic:
                if flag and (i+4) < n:
                    image, box = get_random_data_with_Mosaic(annotation_lines[i:i+4], input_shape)
                    i = (i+1) % n
                else:
                    image, box = get_random_data(annotation_lines[i], input_shape)
                    i = (i+1) % n
                flag = bool(1-flag)
            else:
                image, box = get_random_data(annotation_lines[i], input_shape)
                i = (i+1) % n
            image_data.append(image)
            box_data.append(box)
        image_data = np.array(image_data)
        box_data = np.array(box_data)
        y_true = preprocess_true_boxes(box_data, input_shape, anchors, num_classes)
        yield [image_data, *y_true], np.zeros(batch_size)

def data_generator_wrapper(annotation_lines, batch_size, input_shape, anchors, num_classes, mosaic=False):
    n = len(annotation_lines)
    if n==0 or batch_size<=0: return None
    return data_generator(annotation_lines, batch_size, input_shape, anchors, num_classes,mosaic)

if __name__ == '__main__':
    _main()
