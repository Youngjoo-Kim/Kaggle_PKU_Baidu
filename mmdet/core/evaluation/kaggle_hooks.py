import os
import os.path as osp

import mmcv
import numpy as np
import torch
import torch.distributed as dist
import pandas as pd
from mmcv.parallel import collate, scatter
from mmcv.runner import Hook
from pycocotools.cocoeval import COCOeval
from torch.utils.data import Dataset

from mmdet.datasets.kaggle_pku_utils import quaternion_to_euler_angle
from sklearn.metrics import average_precision_score
from multiprocessing import Pool
from . import DistEvalHook

from mmdet.utils import check_match, coords2str

def match(t):
    return check_match(*t[0])

class KaggleEvalHook(DistEvalHook):

    def __init__(self, dataset, conf_thresh, interval=1):
        self.ann_file = dataset.ann_file
        self.conf_thresh = conf_thresh 

        super(KaggleEvalHook, self).__init__(dataset, interval)

    def evaluate(self, runner, results):
        predictions = {}

        CAR_IDX = 2  # this is the coco car class
        for idx_img, output in enumerate(results):
            # Wudi change the conf to car prediction
            conf = output[0][CAR_IDX][:, -1]  # output [0] is the bbox
            idx = conf > self.conf_thresh

            file_name = os.path.basename(output[2]["file_name"])
            ImageId = ".".join(file_name.split(".")[:-1])

            euler_angle = np.array([quaternion_to_euler_angle(x) for x in output[2]['quaternion_pred']])
            translation = output[2]['trans_pred_world']
            coords = np.hstack((euler_angle[idx], translation[idx], conf[idx, None]))
            coords_str = coords2str(coords)
            predictions[ImageId] = coords_str

        pred_dict = {'ImageId': [], 'PredictionString': []}
        for k, v in predictions.items():
            pred_dict['ImageId'].append(k)
            pred_dict['PredictionString'].append(v)

        train_df = pd.DataFrame(data=pred_dict)
        valid_df = pd.read_csv(self.ann_file)
        max_workers = 1
        
        n_gt = len(train_df)
        ap_list = []
        p = Pool(processes=max_workers)

        for result_flg, scores in p.imap(match, 
                                         zip([(i, train_df, valid_df) for i in range(10)])):
            if np.sum(result_flg) > 0:
                n_tp = np.sum(result_flg)
                recall = n_tp / n_gt
                ap = average_precision_score(result_flg, scores) * recall
            else:
                ap = 0
            ap_list.append(ap)
        mean_ap = np.mean(ap_list)
        print(mean_ap)
        runner.log_buffer.output['valuation_mAP'] = mean_ap
        runner.log_buffer.ready = True




