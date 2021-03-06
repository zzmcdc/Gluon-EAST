# coding=utf-8
import mxnet as mx
from mxnet import gluon, autograd
import gluoncv as gcv
from model_zoo import east, EASTLoss, east_fpn
from data.ic_data import text_detection_data
from mxnet.gluon.data import DataLoader
from mxnet.gluon import utils
import logging
import os, sys
from mxboard import SummaryWriter
import numpy as np
from mxnet import lr_scheduler as ls

logging.basicConfig(level=logging.INFO)

def main(train_dir, ctx=None, lr=0.0001, epoches=20, batch_size=16, checkpoint_path='model', debug=False):
    summ_writer = SummaryWriter(checkpoint_path)
    # dataloader
    ctx = eval(ctx)
    context = mx.gpu(ctx) if ctx > 0 else mx.cpu()
    ic_data = text_detection_data(image_dir=train_dir)
    ic_dataloader = DataLoader(dataset=ic_data, batch_size=batch_size, shuffle=True, num_workers=16)
    data_num = len(ic_dataloader) * batch_size
    # model
    east_model = east.EAST(nclass=2, text_scale=1024)
    # east_model = east(text_scale=1024)

    east_model.collect_params().initialize(init=mx.init.Xavier(), verbose=True, ctx=context)
    if not debug:
        east_model.hybridize()
    cos_shc = ls.PolyScheduler(max_update=ic_dataloader.length * epoches//batch_size, base_lr=lr)

    trainer = gluon.Trainer(east_model.collect_params(),
                            'sgd',
                            {'learning_rate': lr,
                             'wd': 1e-5,
                             'momentum': 0.9,
                             'clip_gradient': 5,
                             'lr_scheduler':cos_shc}
                            )
    EAST_loss = EASTLoss(cls_weight=0.01, iou_weight=1.0, angle_weight=20)
    step = 0
    lr_counter = 0
    lr_steps = [5, 10, 15, 20]
    lr_factor = 0.9

    for epoch in range(epoches):
        loss = []
        if epoch == lr_steps[lr_counter]:
            trainer.set_learning_rate(trainer.learning_rate*lr_factor)
            lr_counter += 1
        for i, batch_data in enumerate(ic_dataloader):
            im, score_map, geo_map, training_mask = map(lambda x: x.as_in_context(ctx), batch_data)

            with autograd.record(train_mode=True):

                f_score, f_geo = east_model(im)
                batch_loss = EAST_loss(score_map, f_score, geo_map, f_geo, training_mask)
                loss.append(batch_loss)
                batch_loss.backward()

            trainer.step(batch_size)
            # if i % 2 == 0:
            step = epoch * data_num  + i * batch_size
            model_loss = np.mean(map(lambda x: x.asnumpy()[0], loss))
            summ_writer.add_scalar('model_loss', model_loss[0])
            logging.info("step: {}, loss: {}".format(step, batch_loss.asnumpy()))
        ckpt_file = os.path.join(checkpoint_path, "model_{}.params".format(step))
        east_model.save_parameters(ckpt_file)
        logging.info("save model to {}".format(ckpt_file))

if __name__ == '__main__':
    train_dir = sys.argv[1]
    ckpt_path = sys.argv[2]
    ctxes = sys.argv[3]
    main(train_dir=train_dir, ctx=ctxes, checkpoint_path=ckpt_path, debug=True)
