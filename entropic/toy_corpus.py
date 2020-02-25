from cached_property import cached_property
import random
from itertools import cycle
import numpy as np


class ToyCorpus:
    """
    methods for making a document, a string of artificial words following the structure (xw, yw, xw, yw, ..).
    example document: "x1 y5 x34 y82 x93 y3 x45 y11".
    """

    def __init__(self,
                 doc_size: int = 100_000,
                 num_types: int = 4096,
                 num_xws: int = 512,
                 num_fragments: int = 2,  # number of sub-categories in xws
                 period_probability: float = 0.0,
                 alpha: float = 2.0,
                 ) -> None:
        self.doc_size = doc_size
        self.num_types = num_types
        self.num_xws = num_xws
        self.num_fragments = num_fragments
        self.period_probability = period_probability
        self.alpha = alpha
        self.num_yws = self.num_types - self.num_xws

        self.xws = [f'x{i:0>6}' for i in range(self.num_xws)]
        self.yws = [f'y{i:0>6}' for i in range(self.num_yws)]

        # map subsets of xws to mutually exclusive subsets/fragments of yws
        yw_fragments = [self.yws[offset::num_fragments] for offset in range(num_fragments)]
        c = cycle(yw_fragments)
        self.xw2yws = {xw: next(c) for xw in self.xws}

        self.fragment_size = self.num_yws // self.num_fragments

        # the number of legal joint outcomes is the total number divided by the fragment size
        self.num_possible = self.num_xws*self.num_yws / num_fragments

        print('Initialized ToyCorpus')
        print(f'Lowest theoretical pp ={self.fragment_size:>6,}')
        print(f'Number of y-word types={self.num_yws:>6,}')

    @cached_property
    def doc(self) -> str:
        joint_outcomes = set()

        # make
        pseudo_periods = []
        c = cycle(range(self.num_fragments))
        yw_fragments = [self.yws[offset::self.num_fragments] for offset in range(self.num_fragments)]
        num_max = 8  # should be small - to ensure that joint entropy is smaller in partition 1
        for yw_pop in list(zip(*yw_fragments))[:num_max]:
            i = next(c)
            pseudo_periods.append(yw_pop[i])

        print('pseudo_periods')
        print(pseudo_periods)
        print(sum([1 if pp in self.xw2yws[self.xws[0]] else 0 for pp in pseudo_periods]))
        print(sum([1 if pp in self.xw2yws[self.xws[1]] else 0 for pp in pseudo_periods]))

        # make cumulative weights that mimic power distribution
        logits = [(xi + 1) ** self.alpha for xi in range(len(pseudo_periods))]
        cum_weights = [l / logits[-1] for l in logits]

        res = ''
        for n in range(self.doc_size // 2):  # divide by 2 because each loop adds 2 words

            # sample xw randomly
            xw = random.choice(self.xws)

            # sample yw that is consistent with ALL xw categories (e.g. PERIOD)
            if random.random() < self.period_probability and xw not in self.xws[:2]:
                yw = random.choices(pseudo_periods, cum_weights=cum_weights, k=1)[0]

            # sample yw consistent with xw category
            else:
                yw = random.choice(self.xw2yws[xw])

            # collect
            res += f'{xw} {yw} '  # whitespace after each
            joint_outcomes.add((xw, yw))

        print(f'Number of unique joint outcomes={len(joint_outcomes):,}/{self.num_possible:,}')
        print(f'Coverage={len(joint_outcomes) / self.num_possible:.2f}')

        return res

    @cached_property
    def sim_mat_gold(self) -> np.ndarray:

        # every xw is related to every other xw, depending on num_fragments
        res = np.zeros((self.num_xws, self.num_xws))
        for row_id in range(self.num_xws):
            offset = row_id % self.num_fragments
            res[row_id, offset::self.num_fragments] += 1

        return res