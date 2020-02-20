import attr
import numpy as np
import torch
import sys
from sklearn.metrics.pairwise import cosine_similarity
from torch import optim as optim
import pandas as pd
from pathlib import Path

from straddler.data import Data
from straddler import config
from straddler.eval import calc_cluster_score
from straddler.net import Net
from straddler.utils import to_eval_epochs


@attr.s
class Params(object):
    batch_size = attr.ib(validator=attr.validators.instance_of(int))  # TODO params


    @classmethod
    def from_param2val(cls, param2val):
        """
        instantiate class.
        exclude keys from param2val which are added by Ludwig.
        they are relevant to job submission only.
        """
        kwargs = {k: v for k, v in param2val.items()
                  if k not in ['job_name', 'param_name', 'project_path', 'save_path']}
        return cls(**kwargs)


def main(param2val):

    # params
    params = Params.from_param2val(param2val)
    print(params, flush=True)

    # data
    data = Data(params)

    # net
    net = Net(params, data)

    # optimizer + criterion
    # noinspection PyUnresolvedReferences
    optimizer = optim.SGD(net.parameters(), lr=params.lr)
    criterion = torch.nn.MSELoss()

    # eval before start of training
    # noinspection PyUnresolvedReferences
    net.eval()
    torch_o = net(data.torch_x)
    torch_y = torch.from_numpy(data.make_y(epoch=0))
    loss = criterion(torch_o, torch_y)
    # noinspection PyUnresolvedReferences
    net.train()

    # train loop
    eval_epoch_idx = 0
    scores_a = np.zeros(config.Eval.num_evals)
    scores_b = np.zeros(config.Eval.num_evals)
    eval_epochs = to_eval_epochs(params)
    for epoch in range(params.num_epochs + 1):
        # eval
        if epoch in eval_epochs:
            # cluster score
            print('Evaluating at epoch {}'.format(epoch))
            collect_scores(data, params, net, eval_epoch_idx, scores_a, scores_b, torch_o)
            eval_epoch_idx += 1
            # mse
            mse = loss.detach().numpy().item()
            print('mse={}'.format(mse))
            print()
            sys.stdout.flush()

        y = data.make_y(epoch)

        # train
        optimizer.zero_grad()  # zero the gradient buffers
        torch_o = net(data.torch_x)  # feed-forward
        torch_y = torch.from_numpy(y)
        loss = criterion(torch_o, torch_y)  # compute loss
        loss.backward()  # back-propagate
        optimizer.step()  # update

    # return performance as pandas Series # TODO return series not df
    eval_epochs = to_eval_epochs(params)
    df_a = pd.DataFrame(scores_a, index=eval_epochs, columns=[config.Eval.metric])
    df_b = pd.DataFrame(scores_b, index=eval_epochs, columns=[config.Eval.metric])
    df_a.name = 'results_a'
    df_b.name = 'results_b'

    return df_a, df_b


def collect_scores(data, params, net, eval_epoch_idx, scores_a, scores_b, torch_o):
    # rep_mat
    if params.representation == 'output':
        rep_mat = torch_o.detach().numpy()  # TODO make gif of evolving prediction mat
    elif params.representation == 'hidden':
        rep_mat = net.linear1(data.torch_x).detach().numpy()
    else:
        raise AttributeError('Invalid arg to "representation".')
    #
    rep_mats = [rep_mat[:data.superordinate_size],
                rep_mat[-data.superordinate_size:]]
    rep_mats_gold = [data.y1_gold[:data.superordinate_size],
                     data.y1_gold[-data.superordinate_size:]]
    for scores, rep_mat, rep_mat_gold in zip([scores_a, scores_b], rep_mats, rep_mats_gold):
        if scores[max(0, eval_epoch_idx - 1)] == 1.0:
            continue
        sim_mat = cosine_similarity(rep_mat)
        sim_mat_gold = np.rint(cosine_similarity(rep_mat_gold))
        score = calc_cluster_score(sim_mat, sim_mat_gold, config.Eval.metric)
        scores[eval_epoch_idx] = score
        #
        if score == 1.0:
            scores[eval_epoch_idx:] = 1.0
        #
        print(rep_mat.round(3))
        print(sim_mat_gold.round(1))
        print(sim_mat.round(4))
        print('{}={}'.format(config.Eval.metric, score))