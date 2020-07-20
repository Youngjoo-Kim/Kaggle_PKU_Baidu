#CUDA_VISIBLE_DEVICES=4 FLASK_ENV=development FLASK_APP=interface.py flask run -p 5003
import os
import random
import base64
import io

from PIL import Image
import numpy as np
import cv2

import mmcv
import torch
from mmcv.parallel import MMDataParallel
from mmcv.runner import load_checkpoint
from mmdet.models import build_detector

from mmcv.parallel import collate
from mmdet.datasets.kaggle_pku_utils import quaternion_to_euler_angle
from mmdet.datasets.pipelines import Compose

from flask import Flask
from flask import request, jsonify

app = Flask(__name__)


def init_model():
    config = './configs/htc/htc_hrnetv2p_w48_20e_kaggle_pku_no_semantic_translation_wudi_car_insurance.py'
    checkpoint_path = '/data/Kaggle/checkpoints/all_cwxe99_3070100flip05resumme93Dec29-16-28-48/epoch_100.pth'

    cfg = mmcv.Config.fromfile(config)
    model = build_detector(cfg.model, train_cfg=None, test_cfg=cfg.test_cfg)

    checkpoint = load_checkpoint(model, checkpoint_path, map_location='cpu')
    model.CLASSES = checkpoint['meta']['CLASSES']

    model = MMDataParallel(model, device_ids=[0])
    model.eval()
    return model, cfg


class LoadImage(object):

    def __call__(self, results):
        if isinstance(results['img'], str):
            results['filename'] = results['img']
        else:
            results['filename'] = None
        img = mmcv.imread(results['img'])
        results['img'] = img
        results['img_shape'] = img.shape
        results['ori_shape'] = img.shape
        return results


def format_return_data(output):
    CAR_IDX = 2  # this is the coco car class
    file_name = os.path.basename(output[2]["file_name"])
    ImageId = ".".join(file_name.split(".")[:-1])

    # Wudi change the conf to car prediction
    if len(output[0][CAR_IDX]):
        conf = output[0][CAR_IDX][:, -1]  # output [0] is the bbox
        idx = conf > 0.8
        # if 'euler_angle' in output[2].keys():
        eular_angle = np.array([quaternion_to_euler_angle(x) for x in output[2]['quaternion_pred']])
        translation = output[2]['trans_pred_world']
        coords = np.hstack((output[0][CAR_IDX][idx], eular_angle[idx], translation[idx]))
        return coords


def inference_detector(cfg, model, img):
    """Inference image(s) with the detector.

    Args:
        model (nn.Module): The loaded detector.
        imgs (str/ndarray or list[str/ndarray]): Either image files or loaded
            images.

    Returns:
        If imgs is a str, a generator will be returned, otherwise return the
        detection results directly.
    """
    # build the data pipeline
    test_pipeline = [LoadImage()] + cfg.data.test.pipeline[2:]
    test_pipeline = Compose(test_pipeline)
    # prepare data
    data = dict(img=img)
    data = test_pipeline(data)
    data = collate([data], samples_per_gpu=1)
    # forward the model
    with torch.no_grad():
        result = model(return_loss=False, rescale=True, **data)

    return result


model, cfg = init_model()


# img = './test_img/IMG_20200622_154753.jpg'

# import glob
# file_list = glob.glob("./test_img/*.jpg")
# for img in file_list:
#     result = inference_detector(cfg, model, img)

#     data = format_return_data(result)
#     print(data.shape)

#     if data.shape[0] > 0:
#         dataset = build_dataset(cfg.data.train)
#         image = cv2.imread(img)

#         left_top = (int(data[0, 0]), int(data[0, 1]))
#         right_bottom = (int(data[0, 2]), int(data[0, 3]))
#         cv2.rectangle(image, left_top, right_bottom, 255, thickness=1)

#         cv2.imwrite("test.jpg", image)
#         dataset.visualise_pred_single_image(img, result)

def base64ToRGB(base64_string):
    imgdata = base64.b64decode(str(base64_string))
    image = Image.open(io.BytesIO(imgdata))
    return cv2.cvtColor(np.array(image), cv2.COLOR_BGR2RGB)


@app.route('/', methods=['POST'])
def hello():
    # img = request.files.get('file')
    image_base64 = request.form.get('file')
    # fx = request.form.get('fx')
    image = base64ToRGB(image_base64)

    img_i = random.randint(1, 100000)
    image_path = "./upload_imgs/tmp_{}.jpg".format(img_i)
    cv2.imwrite(image_path, image)
    result = inference_detector(cfg, model, image_path)
    data = format_return_data(result)
    os.remove(image_path)

    if data.shape[0] > 0:
        data = data[0]
        json = dict(
            code=0,
            msg='success',
            x1=data[0],
            y1=data[1],
            x2=data[2],
            y2=data[3],
            conf=data[4],
            rotation=list(data[5:8]),
            translation=list(data[8:]),
        )
    else:
        json = dict(
            status=1,
            msg='NO CAR'
        )
    return jsonify(json)
