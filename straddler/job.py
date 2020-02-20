import attr
import numpy as np
import torch
from sklearn.metrics.pairwise import cosine_similarity
import pandas as pd

from preppy import SlidingPrep

from straddler import config
from straddler.eval import calc_cluster_score
from straddler.toy_corpus import ToyCorpus
from straddler.rnn import RNN


@attr.s
class Params(object):
    # rnn
    hidden_size = attr.ib(validator=attr.validators.instance_of(int))
    # toy corpus
    doc_size = attr.ib(validator=attr.validators.instance_of(int))
    num_xws = attr.ib(validator=attr.validators.instance_of(int))
    num_types = attr.ib(validator=attr.validators.instance_of(int))
    num_fragments = attr.ib(validator=attr.validators.instance_of(int))
    fragmentation_prob = attr.ib(validator=attr.validators.instance_of(float))
    # training
    slide_size = attr.ib(validator=attr.validators.instance_of(int))
    optimizer = attr.ib(validator=attr.validators.instance_of(str))
    batch_size = attr.ib(validator=attr.validators.instance_of(int))
    lr = attr.ib(validator=attr.validators.instance_of(float))

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

    # create toy input
    toy_corpus = ToyCorpus(doc_size=params.doc_size,
                           num_types=params.num_types,
                           num_xws=params.num_xws,
                           num_fragments=params.num_fragments,
                           fragmentation_prob=params.fragmentation_prob,
                           )
    prep = SlidingPrep([toy_corpus.doc],
                       reverse=False,
                       num_types=params.num_types,
                       slide_size=params.slide_size,
                       batch_size=params.batch_size,
                       context_size=1)

    xw_ids = [prep.store.w2id[xw] for xw in toy_corpus.xws]

    rnn = RNN('srn', input_size=params.num_types, hidden_size=params.hidden_size)

    criterion = torch.nn.CrossEntropyLoss()
    if params.optimizer == 'adagrad':
        optimizer = torch.optim.Adagrad(rnn.parameters(), lr=params.lr)
    elif params.optimizer == 'sgd':
        optimizer = torch.optim.SGD(rnn.parameters(), lr=params.lr)
    else:
        raise AttributeError('Invalid arg to "optimizer')

    # train loop
    eval_steps = []
    dps = []
    pps = []
    bas = []
    for step, batch in enumerate(prep.generate_batches()):

        # prepare x, y
        x, y = batch[:, -1, np.newaxis], batch[:, -1]
        inputs = torch.cuda.LongTensor(x)
        targets = torch.cuda.LongTensor(y)  # TODO copying batch to GPU each time is costly

        print(x.shape)
        print(y.shape)

        # ba
        rnn.eval()
        xw_reps = rnn.embed.weight.detach().cpu().numpy()[xw_ids]
        sim_mat = cosine_similarity(xw_reps)

        print(sim_mat.shape)
        print(sim_mat.mean)

        ba = calc_cluster_score(sim_mat, toy_corpus.sim_mat_gold, 'ba')

        # feed-forward + compute loss
        rnn.train()
        logits = rnn(inputs)['logits']  # feed-forward
        optimizer.zero_grad()  # zero the gradient buffers
        loss = criterion(logits, targets)

        # dp
        dp = 0  # TODO calc divergence from prototype: how lexically specific are next word predictions for straddler?

        # console
        pp = torch.exp(loss).detach().cpu().numpy().item()
        print(f'step={step:>6,}: pp={pp:.1f} ba={ba:.4f}', flush=True)
        print()

        # update RNN weights
        loss.backward()
        optimizer.step()

        # collect performance data
        eval_steps.append(step)
        dps.append(dp)
        pps.append(pp)
        bas.append(ba)

    # return performance as pandas Series
    s1 = pd.Series(dps, index=eval_steps)
    s2 = pd.Series(pps, index=eval_steps)
    s3 = pd.Series(bas, index=eval_steps)
    s1.name = 'dp_straddler'
    s2.name = 'pp'
    s3.name = 'ba'

    return s1, s2, s3