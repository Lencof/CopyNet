__author__ = 'jiataogu'

import theano # use theano
import logging # use logging
import copy # use copy
import emolga.basic.objectives as objectives
import emolga.basic.optimizers as optimizers

from theano.compile.nanguardmode import NanGuardMode
from emolga.utils.generic_utils import visualize_
from emolga.layers.core import Dropout, Dense, Dense2, Identity
from emolga.layers.recurrent import *
from emolga.layers.ntm_minibatch import Controller
from emolga.layers.embeddings import *
from emolga.layers.attention import *
from core import Model

logger = logging.getLogger(__name__)
RNN    = GRU             # change it here for other RNN models.
err    = 1e-9


# create class Encode(Model):
class Encoder(Model):
    """
    Recurrent Neural Network-based Encoder
    It is used to compute the context vector.
    """

    # create def __init__
    def __init__(self,
                 config, rng, prefix='enc',
                 mode='Evaluation', embed=None, use_context=False):
        super(Encoder, self).__init__()
        self.config = config
        self.rng = rng
        self.prefix = prefix
        self.mode = mode
        self.name = prefix
        self.use_context = use_context

        self.return_embed = False
        self.return_sequence = False

        """
        Create all elements of the Encoder's Computational graph
        """
        # create Embedding layers
        logger.info("{}_create embedding layers.".format(self.prefix))
        if embed:
            self.Embed = embed
        else:
            self.Embed = Embedding(
                self.config['enc_voc_size'],
                self.config['enc_embedd_dim'],
                name="{}_embed".format(self.prefix))
            self._add(self.Embed)

        if self.use_context:
            self.Initializer = Dense(
                config['enc_contxt_dim'],
                config['enc_hidden_dim'],
                activation='tanh',
                name="{}_init".format(self.prefix)
            )
            self._add(self.Initializer)

        """
        Encoder Core
        """
        # create RNN cells
        if not self.config['bidirectional']:
            logger.info("{}_create RNN cells.".format(self.prefix))
            self.RNN = RNN(
                self.config['enc_embedd_dim'],
                self.config['enc_hidden_dim'],
                None if not use_context
                else self.config['enc_contxt_dim'],
                name="{}_cell".format(self.prefix)
            )
            self._add(self.RNN)
        else:
            logger.info("{}_create forward RNN cells.".format(self.prefix))
            self.forwardRNN = RNN(
                self.config['enc_embedd_dim'],
                self.config['enc_hidden_dim'],
                None if not use_context
                else self.config['enc_contxt_dim'],
                name="{}_fw_cell".format(self.prefix)
            )
            self._add(self.forwardRNN)

            logger.info("{}_create backward RNN cells.".format(self.prefix))
            self.backwardRNN = RNN(
                self.config['enc_embedd_dim'],
                self.config['enc_hidden_dim'],
                None if not use_context
                else self.config['enc_contxt_dim'],
                name="{}_bw_cell".format(self.prefix)
            )
            self._add(self.backwardRNN)

        logger.info("create encoder ok.")

    def build_encoder(self, source, context=None, return_embed=False,
                      return_sequence=False,
                      return_gates=False,
                      clean_mask=False):
        """
        Build the Encoder Computational Graph
        """
        # clean_mask means we set the hidden states of masked places as 0.
        # sometimes it will help the program to solve something
        # note that this option only works when return_sequence.
        # we recommend to leave at least one mask in the end of encoded sequence.

        # Initial state
        Init_h = None
        if self.use_context:
            Init_h = self.Initializer(context)

        # word embedding
        if not self.config['bidirectional']:
            X, X_mask = self.Embed(source, True)
            if return_gates:
                X_out, Z, R = self.RNN(X, X_mask, C=context, init_h=Init_h,
                                       return_sequence=return_sequence,
                                       return_gates=True)
            else:
                X_out     = self.RNN(X, X_mask, C=context, init_h=Init_h,
                                     return_sequence=return_sequence,
                                     return_gates=False)
            if return_sequence:
                X_tail    = X_out[:, -1]

                if clean_mask:
                    X_out     = X_out * X_mask[:, :, None]
            else:
                X_tail    = X_out
        else:
            source2 = source[:, ::-1]
            X,  X_mask = self.Embed(source, True)
            X2, X2_mask = self.Embed(source2, True)

            if not return_gates:
                X_out1 = self.backwardRNN(X, X_mask,  C=context, init_h=Init_h, return_sequence=return_sequence)
                X_out2 = self.forwardRNN(X2, X2_mask, C=context, init_h=Init_h, return_sequence=return_sequence)
            else:
                X_out1, Z1, R1  = self.backwardRNN(X, X_mask,  C=context, init_h=Init_h,
                                                   return_sequence=return_sequence,
                                                   return_gates=True)
                X_out2, Z2, R2  = self.forwardRNN(X2, X2_mask, C=context, init_h=Init_h,
                                                  return_sequence=return_sequence,
                                                  return_gates=True)
                Z = T.concatenate([Z1, Z2[:, ::-1, :]], axis=2)
                R = T.concatenate([R1, R2[:, ::-1, :]], axis=2)

            if not return_sequence:
                X_out  = T.concatenate([X_out1, X_out2], axis=1)
                X_tail = X_out
            else:
                X_out  = T.concatenate([X_out1, X_out2[:, ::-1, :]], axis=2)
                X_tail = T.concatenate([X_out1[:, -1], X_out2[:, -1]], axis=1)

                if clean_mask:
                    X_out     = X_out * X_mask[:, :, None]

        X_mask  = T.cast(X_mask, dtype='float32')
        if not return_gates:
            if return_embed:
                return X_out, X, X_mask, X_tail
            return X_out
        else:
            if return_embed:
                return X_out, X, X_mask, X_tail, Z, R
            return X_out, Z, R

    def compile_encoder(self, with_context=False, return_embed=False, return_sequence=False):
        source  = T.imatrix()
        self.return_embed = return_embed
        self.return_sequence = return_sequence
        if with_context:
            context = T.matrix()

            self.encode = theano.function([source, context],
                                          self.build_encoder(source, context,
                                                             return_embed=return_embed,
                                                             return_sequence=return_sequence))
            self.gtenc  = theano.function([source, context],
                                          self.build_encoder(source, context,
                                                             return_embed=return_embed,
                                                             return_sequence=return_sequence,
                                                             return_gates=True))
        else:
            self.encode = theano.function([source],
                                          self.build_encoder(source, None,
                                                             return_embed=return_embed,
                                                             return_sequence=return_sequence))
            self.gtenc  = theano.function([source],
                                          self.build_encoder(source, None,
                                                             return_embed=return_embed,
                                                             return_sequence=return_sequence,
                                                             return_gates=True))


class Decoder(Model):
    """
    Recurrent Neural Network-based Decoder.
    It is used for:
        (1) Evaluation: compute the probability P(Y|X)
        (2) Prediction: sample the best result based on P(Y|X)
        (3) Beam-search
        (4) Scheduled Sampling (how to implement it?)
    """

    def __init__(self,
                 config, rng, prefix='dec',
                 mode='RNN', embed=None,
                 highway=False):
        """
        mode = RNN: use a RNN Decoder
        """
        super(Decoder, self).__init__()
        self.config = config
        self.rng = rng
        self.prefix = prefix
        self.name = prefix
        self.mode = mode

        self.highway = highway
        self.init = initializations.get('glorot_uniform')
        self.sigmoid = activations.get('sigmoid')

        # use standard drop-out for input & output.
        # I believe it should not use for context vector.
        self.dropout = config['dropout']
        if self.dropout > 0:
            logger.info('Use standard-dropout!!!!')
            self.D   = Dropout(rng=self.rng, p=self.dropout, name='{}_Dropout'.format(prefix))

        """
        Create all elements of the Decoder's computational graph.
        """
        # create Embedding layers
        logger.info("{}_create embedding layers.".format(self.prefix))
        if embed:
            self.Embed = embed
        else:
            self.Embed = Embedding(
                self.config['dec_voc_size'],
                self.config['dec_embedd_dim'],
                name="{}_embed".format(self.prefix))
            self._add(self.Embed)

        # create Initialization Layers
        logger.info("{}_create initialization layers.".format(self.prefix))
        if not config['bias_code']:
            self.Initializer = Zero()
        else:
            self.Initializer = Dense(
                config['dec_contxt_dim'],
                config['dec_hidden_dim'],
                activation='tanh',
                name="{}_init".format(self.prefix)
            )

        # create RNN cells
        logger.info("{}_create RNN cells.".format(self.prefix))
        if 'location_embed' in self.config:
            if config['location_embed']:
                dec_embedd_dim = 2 * self.config['dec_embedd_dim']
            else:
                dec_embedd_dim = self.config['dec_embedd_dim']
        else:
            dec_embedd_dim = self.config['dec_embedd_dim']

        self.RNN = RNN(
            dec_embedd_dim,
            self.config['dec_hidden_dim'],
            self.config['dec_contxt_dim'],
            name="{}_cell".format(self.prefix)
        )

        self._add(self.Initializer)
        self._add(self.RNN)

        # HighWay Gating
        if highway:
            logger.info("HIGHWAY CONNECTION~~~!!!")
            assert self.config['context_predict']
            assert self.config['dec_contxt_dim'] == self.config['dec_hidden_dim']

            self.C_x = self.init((self.config['dec_contxt_dim'],
                                  self.config['dec_hidden_dim']))
            self.H_x = self.init((self.config['dec_hidden_dim'],
                                  self.config['dec_hidden_dim']))
            self.b_x = initializations.get('zero')(self.config['dec_hidden_dim'])

            self.C_x.name = '{}_Cx'.format(self.prefix)
            self.H_x.name = '{}_Hx'.format(self.prefix)
            self.b_x.name = '{}_bx'.format(self.prefix)
            self.params += [self.C_x, self.H_x, self.b_x]

        # create readout layers
        logger.info("_create Readout layers")

        # 1. hidden layers readout.
        self.hidden_readout = Dense(
            self.config['dec_hidden_dim'],
            self.config['output_dim']
            if self.config['deep_out']
            else self.config['dec_voc_size'],
            activation='linear',
            name="{}_hidden_readout".format(self.prefix)
        )

        # 2. previous word readout
        self.prev_word_readout = None
        if self.config['bigram_predict']:
            self.prev_word_readout = Dense(
                dec_embedd_dim,
                self.config['output_dim']
                if self.config['deep_out']
                else self.config['dec_voc_size'],
                activation='linear',
                name="{}_prev_word_readout".format(self.prefix),
                learn_bias=False
            )

        # 3. context readout
        self.context_readout = None
        if self.config['context_predict']:
            if not self.config['leaky_predict']:
                self.context_readout = Dense(
                    self.config['dec_contxt_dim'],
                    self.config['output_dim']
                    if self.config['deep_out']
                    else self.config['dec_voc_size'],
                    activation='linear',
                    name="{}_context_readout".format(self.prefix),
                    learn_bias=False
                )
            else:
                assert self.config['dec_contxt_dim'] == self.config['dec_hidden_dim']
                self.context_readout = self.hidden_readout

        # option: deep output (maxout)
        if self.config['deep_out']:
            self.activ = Activation(config['deep_out_activ'])
            # self.dropout = Dropout(rng=self.rng, p=config['dropout'])
            self.output_nonlinear = [self.activ]  # , self.dropout]
            self.output = Dense(
                self.config['output_dim'] / 2
                if config['deep_out_activ'] == 'maxout2'
                else self.config['output_dim'],

                self.config['dec_voc_size'],
                activation='softmax',
                name="{}_output".format(self.prefix),
                learn_bias=False
            )
        else:
            self.output_nonlinear = []
            self.output = Activation('softmax')

        # registration:
        self._add(self.hidden_readout)

        if not self.config['leaky_predict']:
            self._add(self.context_readout)

        self._add(self.prev_word_readout)
        self._add(self.output)

        if self.config['deep_out']:
            self._add(self.activ)
        # self._add(self.dropout)

        logger.info("create decoder ok.")

    @staticmethod
    def _grab_prob(probs, X, block_unk=False):
        assert probs.ndim == 3

        batch_size = probs.shape[0]
        max_len = probs.shape[1]
        vocab_size = probs.shape[2]

        probs = probs.reshape((batch_size * max_len, vocab_size))
        return probs[T.arange(batch_size * max_len), X.flatten(1)].reshape(X.shape)  # advanced indexing

    """
    Build the decoder for evaluation
    """
    def prepare_xy(self, target):
        # Word embedding
        Y, Y_mask = self.Embed(target, True)  # (nb_samples, max_len, embedding_dim)

        if self.config['use_input']:
            X = T.concatenate([alloc_zeros_matrix(Y.shape[0], 1, Y.shape[2]), Y[:, :-1, :]], axis=1)
        else:
            X = 0 * Y

        # option ## drop words.

        X_mask    = T.concatenate([T.ones((Y.shape[0], 1)), Y_mask[:, :-1]], axis=1)
        Count     = T.cast(T.sum(X_mask, axis=1), dtype=theano.config.floatX)
        return X, X_mask, Y, Y_mask, Count

    def build_decoder(self, target, context=None,
                      return_count=False,
                      train=True):

        """
        Build the Decoder Computational Graph
        For training/testing
        """
        X, X_mask, Y, Y_mask, Count = self.prepare_xy(target)

        # input drop-out if any.
        if self.dropout > 0:
            X = self.D(X, train=train)

        # Initial state of RNN
        Init_h = self.Initializer(context)
        if not self.highway:
            X_out  = self.RNN(X, X_mask, C=context, init_h=Init_h, return_sequence=True)

            # Readout
            readout = self.hidden_readout(X_out)
            if self.dropout > 0:
                readout = self.D(readout, train=train)

            if self.config['context_predict']:
                readout += self.context_readout(context).dimshuffle(0, 'x', 1)
        else:
            X      = X.dimshuffle((1, 0, 2))
            X_mask = X_mask.dimshuffle((1, 0))

            def _recurrence(x, x_mask, prev_h, c):
                # compute the highway gate for context vector.
                xx    = dot(c, self.C_x, self.b_x) + dot(prev_h, self.H_x)  # highway gate.
                xx    = self.sigmoid(xx)

                cy    = xx * c   # the path without using RNN
                x_out = self.RNN(x, mask=x_mask, C=c, init_h=prev_h, one_step=True)
                hx    = (1 - xx) * x_out
                return x_out, hx, cy

            outputs, _ = theano.scan(
                _recurrence,
                sequences=[X, X_mask],
                outputs_info=[Init_h, None, None],
                non_sequences=[context]
            )

            # hidden readout + context readout
            readout   = self.hidden_readout( outputs[1].dimshuffle((1, 0, 2)))
            if self.dropout > 0:
                readout = self.D(readout, train=train)

            readout  += self.context_readout(outputs[2].dimshuffle((1, 0, 2)))

            # return to normal size.
            X      = X.dimshuffle((1, 0, 2))
            X_mask = X_mask.dimshuffle((1, 0))

        if self.config['bigram_predict']:
            readout += self.prev_word_readout(X)

        for l in self.output_nonlinear:
            readout = l(readout)

        prob_dist = self.output(readout)  # (nb_samples, max_len, vocab_size)
        # log_old  = T.sum(T.log(self._grab_prob(prob_dist, target)), axis=1)
        log_prob = T.sum(T.log(self._grab_prob(prob_dist, target) + err) * X_mask, axis=1)
        log_ppl  = log_prob / Count

        if return_count:
            return log_prob, Count
        else:
            return log_prob, log_ppl

    """
    Sample one step
    """

    def _step_sample(self, prev_word, prev_stat, context):
        # word embedding (note that for the first word, embedding should be all zero)
        if self.config['use_input']:
            X = T.switch(
                prev_word[:, None] < 0,
                alloc_zeros_matrix(prev_word.shape[0], self.config['dec_embedd_dim']),
                self.Embed(prev_word)
            )
        else:
            X = alloc_zeros_matrix(prev_word.shape[0], self.config['dec_embedd_dim'])

        if self.dropout > 0:
            X = self.D(X, train=False)

        # apply one step of RNN
        if not self.highway:
            X_proj = self.RNN(X, C=context, init_h=prev_stat, one_step=True)
            next_stat = X_proj

            # compute the readout probability distribution and sample it
            # here the readout is a matrix, different from the learner.
            readout = self.hidden_readout(next_stat)
            if self.dropout > 0:
                readout = self.D(readout, train=False)

            if self.config['context_predict']:
                readout += self.context_readout(context)
        else:
            xx     = dot(context, self.C_x, self.b_x) + dot(prev_stat, self.H_x)  # highway gate.
            xx     = self.sigmoid(xx)

            X_proj = self.RNN(X, C=context, init_h=prev_stat, one_step=True)
            next_stat = X_proj

            readout  = self.hidden_readout((1 - xx) * X_proj)
            if self.dropout > 0:
                readout = self.D(readout, train=False)

            readout += self.context_readout(xx * context)

        if self.config['bigram_predict']:
            readout += self.prev_word_readout(X)

        for l in self.output_nonlinear:
            readout = l(readout)

        next_prob = self.output(readout)
        next_sample = self.rng.multinomial(pvals=next_prob).argmax(1)
        return next_prob, next_sample, next_stat

    """
    Build the sampler for sampling/greedy search/beam search
    """

    def build_sampler(self):
        """
        Build a sampler which only steps once.
        Typically it only works for one word a time?
        """
        logger.info("build sampler ...")
        if self.config['sample_stoch'] and self.config['sample_argmax']:
            logger.info("use argmax search!")
        elif self.config['sample_stoch'] and (not self.config['sample_argmax']):
            logger.info("use stochastic sampling!")
        elif self.config['sample_beam'] > 1:
            logger.info("use beam search! (beam_size={})".format(self.config['sample_beam']))

        # initial state of our Decoder.
        context = T.matrix()  # theano variable.

        init_h = self.Initializer(context)
        logger.info('compile the function: get_init_state')
        self.get_init_state \
            = theano.function([context], init_h, name='get_init_state')
        logger.info('done.')

        # word sampler: 1 x 1
        prev_word = T.vector('prev_word', dtype='int64')
        prev_stat = T.matrix('prev_state', dtype='float32')
        next_prob, next_sample, next_stat \
            = self._step_sample(prev_word, prev_stat, context)

        # next word probability
        logger.info('compile the function: sample_next')
        inputs = [prev_word, prev_stat, context]
        outputs = [next_prob, next_sample, next_stat]

        self.sample_next = theano.function(inputs, outputs, name='sample_next')
        logger.info('done')
        pass

    """
    Build a Stochastic Sampler which can use SCAN to work on GPU.
    However it cannot be used in Beam-search.
    """

    def build_stochastic_sampler(self):
        context = T.matrix()
        init_h = self.Initializer(context)

        logger.info('compile the function: sample')
        pass

    """
    Generate samples, either with stochastic sampling or beam-search!
    """

    def get_sample(self, context, k=1, maxlen=30, stochastic=True, argmax=False, fixlen=False):
        # beam size
        if k > 1:
            assert not stochastic, 'Beam search does not support stochastic sampling!!'

        # fix length cannot use beam search
        # if fixlen:
        #     assert k == 1

        # prepare for searching
        sample = []
        score = []
        if stochastic:
            score = 0

        live_k = 1
        dead_k = 0

        hyp_samples = [[]] * live_k
        hyp_scores = np.zeros(live_k).astype(theano.config.floatX)
        hyp_states = []

        # get initial state of decoder RNN with context
        next_state = self.get_init_state(context)
        next_word = -1 * np.ones((1,)).astype('int64')  # indicator for the first target word (bos target)

        # Start searching!
        for ii in xrange(maxlen):
            # print next_word
            ctx = np.tile(context, [live_k, 1])
            next_prob, next_word, next_state \
                = self.sample_next(next_word, next_state, ctx)  # wtf.

            if stochastic:
                # using stochastic sampling (or greedy sampling.)
                if argmax:
                    nw = next_prob[0].argmax()
                    next_word[0] = nw
                else:
                    nw = next_word[0]

                sample.append(nw)
                score += next_prob[0, nw]

                if (not fixlen) and (nw == 0):  # sample reached the end
                    break

            else:
                # using beam-search
                # we can only computed in a flatten way!
                cand_scores = hyp_scores[:, None] - np.log(next_prob)
                cand_flat = cand_scores.flatten()
                ranks_flat = cand_flat.argsort()[:(k - dead_k)]

                # fetch the best results.
                voc_size = next_prob.shape[1]
                trans_index = ranks_flat / voc_size
                word_index = ranks_flat % voc_size
                costs = cand_flat[ranks_flat]

                # get the new hyp samples
                new_hyp_samples = []
                new_hyp_scores = np.zeros(k - dead_k).astype(theano.config.floatX)
                new_hyp_states = []

                for idx, [ti, wi] in enumerate(zip(trans_index, word_index)):
                    new_hyp_samples.append(hyp_samples[ti] + [wi])
                    new_hyp_scores[idx] = copy.copy(costs[idx])
                    new_hyp_states.append(copy.copy(next_state[ti]))

                # check the finished samples
                new_live_k = 0
                hyp_samples = []
                hyp_scores = []
                hyp_states = []

                for idx in xrange(len(new_hyp_samples)):
                    if (new_hyp_states[idx][-1] == 0) and (not fixlen):
                        sample.append(new_hyp_samples[idx])
                        score.append(new_hyp_scores[idx])
                        dead_k += 1
                    else:
                        new_live_k += 1
                        hyp_samples.append(new_hyp_samples[idx])
                        hyp_scores.append(new_hyp_scores[idx])
                        hyp_states.append(new_hyp_states[idx])

                hyp_scores = np.array(hyp_scores)
                live_k = new_live_k

                if new_live_k < 1:
                    break
                if dead_k >= k:
                    break

                next_word = np.array([w[-1] for w in hyp_samples])
                next_state = np.array(hyp_states)
                pass
            pass

        # end.
        if not stochastic:
            # dump every remaining one
            if live_k > 0:
                for idx in xrange(live_k):
                    sample.append(hyp_samples[idx])
                    score.append(hyp_scores[idx])

        return sample, score


class DecoderAtt(Decoder):
    """
    Recurrent Neural Network-based Decoder [for CopyNet-b Only]
    with Attention Mechanism
    """
    def __init__(self,
                 config, rng, prefix='dec',
                 mode='RNN', embed=None,
                 copynet=False, identity=False):
        super(DecoderAtt, self).__init__(
                config, rng, prefix,
                 mode, embed, False)
        self.init     = initializations.get('glorot_uniform')
        self.copynet  = copynet
        self.identity = identity
        # attention reader
        self.attention_reader = Attention(
            self.config['dec_hidden_dim'],
            self.config['dec_contxt_dim'],
            1000,
            name='source_attention',
            coverage=self.config['coverage']
        )
        self._add(self.attention_reader)

        # if use copynet
        if self.copynet:
            if not self.identity:
                self.Is = Dense(
                    self.config['dec_contxt_dim'],
                    self.config['dec_embedd_dim'],
                    name='in-trans'
                )
            else:
                assert self.config['dec_contxt_dim'] == self.config['dec_embedd_dim']
                self.Is = Identity(name='ini')

            self.Os = Dense(
                self.config['dec_readout_dim']
                if not self.config['location_embed']
                    else self.config['dec_readout_dim'] + self.config['dec_embedd_dim'],
                self.config['dec_contxt_dim'],
                name='out-trans'
            )

            if self.config['copygate']:
                self.Gs = Dense(
                    self.config['dec_readout_dim'] + self.config['dec_embedd_dim'],
                    1,
                    name='copy-gate',
                    activation='linear',
                    learn_bias=True,
                    negative_bias=True
                )
                self._add(self.Gs)

            if self.config['location_embed']:
                self._add(self.Is)
            self._add(self.Os)

        logger.info('adjust decoder ok.')

    """
    Build the decoder for evaluation
    """
    def prepare_xy(self, target, cc_matrix):
        # target:      (nb_samples, index_seq)
        # cc_matrix:   (nb_samples, maxlen_t, maxlen_s)
        # context:     (nb_samples)
        Y,  Y_mask  = self.Embed(target, True)  # (nb_samples, maxlen_t, embedding_dim)
        X           = T.concatenate([alloc_zeros_matrix(Y.shape[0], 1, Y.shape[2]), Y[:, :-1, :]], axis=1)

        # LL          = T.concatenate([alloc_zeros_matrix(Y.shape[0], 1, cc_matrix.shape[2]),
        #                              cc_matrix[:, :-1, :]], axis=1)
        LL = cc_matrix

        XL_mask     = T.cast(T.gt(T.sum(LL, axis=2), 0), dtype='float32')
        if not self.config['use_input']:
            X *= 0

        X_mask    = T.concatenate([T.ones((Y.shape[0], 1)), Y_mask[:, :-1]], axis=1)
        Count     = T.cast(T.sum(X_mask, axis=1), dtype=theano.config.floatX)
        return X, X_mask, LL, XL_mask, Y_mask, Count

    """
    The most different part. Be caution !!
    Very different from traditional RNN search.
    """
    def build_decoder(self,
                      target,
                      cc_matrix,
                      context,
                      c_mask,
                      return_count=False,
                      train=True):
        """
        Build the Computational Graph ::> Context is essential
        """
        assert c_mask is not None, 'context must be supplied for this decoder.'
        assert context.ndim == 3, 'context must have 3 dimentions.'
        # context: (nb_samples, max_len, contxt_dim)
        context_A = self.Is(context)  # (nb_samples, max_len, embed_dim)
        X, X_mask, LL, XL_mask, Y_mask, Count = self.prepare_xy(target, cc_matrix)

        # input drop-out if any.
        if self.dropout > 0:
            X     = self.D(X, train=train)

        # Initial state of RNN
        Init_h   = self.Initializer(context[:, 0, :])  # default order ->
        Init_a   = T.zeros((context.shape[0], context.shape[1]), dtype='float32')
        coverage = T.zeros((context.shape[0], context.shape[1]), dtype='float32')

        X        = X.dimshuffle((1, 0, 2))
        X_mask   = X_mask.dimshuffle((1, 0))
        LL       = LL.dimshuffle((1, 0, 2))            # (maxlen_t, nb_samples, maxlen_s)
        XL_mask  = XL_mask.dimshuffle((1, 0))          # (maxlen_t, nb_samples)

        def _recurrence(x, x_mask, ll, xl_mask, prev_h, prev_a, cov, cc, cm, ca):
            """
            x:      (nb_samples, embed_dims)
            x_mask: (nb_samples, )
            ll:     (nb_samples, maxlen_s)
            xl_mask:(nb_samples, )
            -----------------------------------------
            prev_h: (nb_samples, hidden_dims)
            prev_a: (nb_samples, maxlen_s)
            cov:    (nb_samples, maxlen_s)  *** coverage ***
            -----------------------------------------
            cc:     (nb_samples, maxlen_s, cxt_dim)
            cm:     (nb_samples, maxlen_s)
            ca:     (nb_samples, maxlen_s, ebd_dim)
            """
            # compute the attention and get the context vector
            prob  = self.attention_reader(prev_h, cc, Smask=cm, Cov=cov)
            ncov  = cov + prob

            cxt   = T.sum(cc * prob[:, :, None], axis=1)

            # compute input word embedding (mixed)
            x_in  = T.concatenate([x, T.sum(ca * prev_a[:, :, None], axis=1)], axis=-1)

            # compute the current hidden states of the RNN.
            x_out = self.RNN(x_in, mask=x_mask, C=cxt, init_h=prev_h, one_step=True)

            # compute the current readout vector.
            r_in  = [x_out]
            if self.config['context_predict']:
                r_in  += [cxt]
            if self.config['bigram_predict']:
                r_in  += [x_in]

            # copynet decoding
            r_in    = T.concatenate(r_in, axis=-1)
            r_out = self.hidden_readout(x_out)  # (nb_samples, voc_size)
            if self.config['context_predict']:
                r_out += self.context_readout(cxt)
            if self.config['bigram_predict']:
                r_out += self.prev_word_readout(x_in)

            for l in self.output_nonlinear:
                r_out = l(r_out)

            key     = self.Os(r_in)  # (nb_samples, cxt_dim) :: key
            Eng     = T.sum(key[:, None, :] * cc, axis=-1)

            # # gating
            if self.config['copygate']:
                gt     = self.sigmoid(self.Gs(r_in))  # (nb_samples, 1)
                r_out += T.log(gt.flatten()[:, None])
                Eng   += T.log(1 - gt.flatten()[:, None])

                # r_out *= gt.flatten()[:, None]
                # Eng   *= 1 - gt.flatten()[:, None]

            EngSum  = logSumExp(Eng, axis=-1, mask=cm, c=r_out)

            next_p  = T.concatenate([T.exp(r_out - EngSum), T.exp(Eng - EngSum) * cm], axis=-1)
            next_c  = next_p[:, self.config['dec_voc_size']:] * ll           # (nb_samples, maxlen_s)
            next_b  = next_p[:, :self.config['dec_voc_size']]
            sum_a   = T.sum(next_c, axis=1, keepdims=True)                   # (nb_samples,)
            next_a  = (next_c / (sum_a + err)) * xl_mask[:, None]            # numerically consideration
            return x_out, next_a, ncov, sum_a, next_b

        outputs, _ = theano.scan(
            _recurrence,
            sequences=[X, X_mask, LL, XL_mask],
            outputs_info=[Init_h, Init_a, coverage, None, None],
            non_sequences=[context, c_mask, context_A]
        )
        X_out, source_prob, coverages, source_sum, prob_dist = [z.dimshuffle((1, 0, 2)) for z in outputs]
        X        = X.dimshuffle((1, 0, 2))
        X_mask   = X_mask.dimshuffle((1, 0))
        XL_mask  = XL_mask.dimshuffle((1, 0))

        # unk masking
        U_mask   = T.ones_like(target) * (1 - T.eq(target, 1))
        U_mask  += (1 - U_mask) * (1 - XL_mask)

        # The most different part is here !!
        log_prob = T.sum(T.log(
                self._grab_prob(prob_dist, target) * U_mask +
                source_sum.sum(axis=-1) + err
        ) * X_mask, axis=1)
        log_ppl  = log_prob / (Count + err)

        if return_count:
            return log_prob, Count
        else:
            return log_prob, log_ppl

    """
    Sample one step
    """

    def _step_sample(self,
                     prev_word,
                     prev_stat,
                     prev_loc,
                     prev_cov,
                     context,
                     c_mask,
                     context_A):

        assert c_mask is not None, 'we need the source mask.'
        # word embedding (note that for the first word, embedding should be all zero)
        X = T.switch(
            prev_word[:, None] < 0,
            alloc_zeros_matrix(prev_word.shape[0], 2 * self.config['dec_embedd_dim']),
            T.concatenate([self.Embed(prev_word),
                           T.sum(context_A * prev_loc[:, :, None], axis=1)
                           ], axis=-1)
        )

        if self.dropout > 0:
            X = self.D(X, train=False)

        # apply one step of RNN
        Probs  = self.attention_reader(prev_stat, context, c_mask, Cov=prev_cov)
        ncov   = prev_cov + Probs

        cxt    = T.sum(context * Probs[:, :, None], axis=1)

        X_proj, zz, rr = self.RNN(X, C=cxt,
                                  init_h=prev_stat,
                                  one_step=True,
                                  return_gates=True)
        next_stat = X_proj

        # compute the readout probability distribution and sample it
        # here the readout is a matrix, different from the learner.
        readin      = [next_stat]
        if self.config['context_predict']:
            readin += [cxt]
        if self.config['bigram_predict']:
            readin += [X]
        readin      = T.concatenate(readin, axis=-1)

        # if gating
        # if self.config['copygate']:
        #     gt      = self.sigmoid(self.Gs(readin))   # (nb_samples, dim)
        #     readin *= 1 - gt
        #     readout = self.hidden_readout(next_stat * gt[:, :self.config['dec_hidden_dim']])
        #     if self.config['context_predict']:
        #         readout += self.context_readout(
        #                 cxt * gt[:, self.config['dec_hidden_dim']:
        #                          self.config['dec_hidden_dim'] + self.config['dec_contxt_dim']])
        #     if self.config['bigram_predict']:
        #         readout += self.prev_word_readout(
        #                 X * gt[:, -2 * self.config['dec_embedd_dim']:])
        # else:
        readout = self.hidden_readout(next_stat)
        if self.config['context_predict']:
            readout += self.context_readout(cxt)
        if self.config['bigram_predict']:
            readout += self.prev_word_readout(X)

        for l in self.output_nonlinear:
            readout = l(readout)

        key         = self.Os(readin)
        Eng         = T.sum(key[:, None, :] * context, axis=-1)

        # # gating
        if self.config['copygate']:
            gt       = self.sigmoid(self.Gs(readin))  # (nb_samples, 1)
            readout += T.log(gt.flatten()[:, None])
            Eng     += T.log(1 - gt.flatten()[:, None])

        EngSum      = logSumExp(Eng, axis=-1, mask=c_mask, c=readout)

        next_prob   = T.concatenate([T.exp(readout - EngSum), T.exp(Eng - EngSum) * c_mask], axis=-1)
        next_sample = self.rng.multinomial(pvals=next_prob).argmax(1)
        return next_prob, next_sample, next_stat, ncov, next_stat

    def build_sampler(self):
        """
        Build a sampler which only steps once.
        Typically it only works for one word a time?
        """
        logger.info("build sampler ...")
        if self.config['sample_stoch'] and self.config['sample_argmax']:
            logger.info("use argmax search!")
        elif self.config['sample_stoch'] and (not self.config['sample_argmax']):
            logger.info("use stochastic sampling!")
        elif self.config['sample_beam'] > 1:
            logger.info("use beam search! (beam_size={})".format(self.config['sample_beam']))

        # initial state of our Decoder.
        context   = T.tensor3()  # theano variable.
        c_mask    = T.matrix()   # mask of the input sentence.
        context_A = self.Is(context)

        init_h = self.Initializer(context[:, 0, :])
        init_a = T.zeros((context.shape[0], context.shape[1]))
        cov    = T.zeros((context.shape[0], context.shape[1]))

        logger.info('compile the function: get_init_state')
        self.get_init_state \
            = theano.function([context], [init_h, init_a, cov], name='get_init_state')
        logger.info('done.')

        # word sampler: 1 x 1
        prev_word = T.vector('prev_word', dtype='int64')
        prev_stat = T.matrix('prev_state', dtype='float32')
        prev_a    = T.matrix('prev_a', dtype='float32')
        prev_cov  = T.matrix('prev_cov', dtype='float32')

        next_prob, next_sample, next_stat, ncov, alpha \
            = self._step_sample(prev_word,
                                prev_stat,
                                prev_a,
                                prev_cov,
                                context,
                                c_mask,
                                context_A)

        # next word probability
        logger.info('compile the function: sample_next')
        inputs  = [prev_word, prev_stat, prev_a, prev_cov, context, c_mask]
        outputs = [next_prob, next_sample, next_stat, ncov, alpha]
        self.sample_next = theano.function(inputs, outputs, name='sample_next')
        logger.info('done')

    """
    Generate samples, either with stochastic sampling or beam-search!

    [:-:] I have to think over how to modify the BEAM-Search!!
    """
    def get_sample(self,
                   context,
                   c_mask,
                   source,
                   k=1, maxlen=30, stochastic=True,
                   argmax=False, fixlen=False,
                   return_attend=False
                   ):
        # beam size
        if k > 1:
            assert not stochastic, 'Beam search does not support stochastic sampling!!'

        # fix length cannot use beam search
        # if fixlen:
        #     assert k == 1

        # prepare for searching
        Lmax   = self.config['dec_voc_size']
        sample = []
        ppp    = []
        attend = []
        score  = []

        if stochastic:
            score = 0

        live_k = 1
        dead_k = 0

        hyp_samples = [[]] * live_k
        hyp_scores  = np.zeros(live_k).astype(theano.config.floatX)
        hyp_ppps    = [[]] * live_k
        hyp_attends = [[]] * live_k

        # get initial state of decoder RNN with context
        next_state, ss_prob, coverage = self.get_init_state(context)
        next_word = -1 * np.ones((1,)).astype('int64')  # indicator for the first target word (bos target)

        # Start searching!
        for ii in xrange(maxlen):
            # print next_word
            ctx    = np.tile(context, [live_k, 1, 1])
            cmk    = np.tile(c_mask,  [live_k, 1])
            sss    = np.tile(source,  [live_k, 1])

            # # process word
            def process_():
                # caution for index_0: UNK
                ll  = np.zeros((sss.shape[0], sss.shape[1]), dtype='float32')
                for i in xrange(next_word.shape[0]):
                    if next_word[i] >= Lmax:
                        ll[i][next_word[i] - Lmax] = 1.
                        next_word[i] = sss[i][next_word[i] - Lmax]
                    else:
                        ll[i] = (sss[i] == next_word[i, None])
                        # for k in xrange(sss.shape[1]):
                        #     ll[i][k] = (sss[i][k] == next_word[i])
                return ll, next_word

            # print next_word
            ll, next_word = process_()
            ll_mask = (np.sum(ll, axis=1, keepdims=True) > 0)

            next_a  = ss_prob * ll
            next_a  = next_a / (err + np.sum(next_a, axis=1, keepdims=True)) * ll_mask
            next_prob0, next_word, next_state, coverage, alpha \
                = self.sample_next(next_word, next_state, next_a, coverage, ctx, cmk)
            # print next_prob0.shape[1]
            if not self.config['decode_unk']:
                next_prob0[:, 1]          = 0.
                next_prob0 /= np.sum(next_prob0, axis=1, keepdims=True)

            def merge_():
                # merge the probabilities
                temple_prob  = copy.copy(next_prob0)
                source_prob  = copy.copy(next_prob0[:, Lmax:])
                for i in xrange(next_prob0.shape[0]):
                    for j in xrange(sss.shape[1]):
                        if (sss[i, j] < Lmax) and (sss[i, j] != 1):
                            temple_prob[i, sss[i, j]] += source_prob[i, j]
                            temple_prob[i, Lmax + j]   = 0.

                return temple_prob, source_prob

            next_prob, ss_prob   = merge_()
            next_prob0[:, Lmax:] = 0.
            # print '0', next_prob0[:, 3165]
            # print '01', next_prob[:, 3165]
            # # print next_prob[0, Lmax:]
            # print ss_prob[0, :]

            if stochastic:
                # using stochastic sampling (or greedy sampling.)
                if argmax:
                    nw = next_prob[0].argmax()
                    next_word[0] = nw
                else:
                    nw = self.rng.multinomial(pvals=next_prob).argmax(1)

                sample.append(nw)
                score += next_prob[0, nw]

                if (not fixlen) and (nw == 0):  # sample reached the end
                    break

            else:
                # using beam-search
                # we can only computed in a flatten way!
                cand_scores = hyp_scores[:, None] - np.log(next_prob)
                cand_flat   = cand_scores.flatten()
                ranks_flat  = cand_flat.argsort()[:(k - dead_k)]

                # fetch the best results.
                voc_size    = next_prob.shape[1]
                trans_index = ranks_flat / voc_size
                word_index  = ranks_flat % voc_size
                costs       = cand_flat[ranks_flat]

                # get the new hyp samples
                new_hyp_samples  = []
                new_hyp_ppps     = []
                new_hyp_attends  = []
                new_hyp_scores   = np.zeros(k - dead_k).astype(theano.config.floatX)
                new_hyp_states   = []
                new_hyp_coverage = []
                new_hyp_ss       = []

                for idx, [ti, wi] in enumerate(zip(trans_index, word_index)):
                    new_hyp_samples.append(hyp_samples[ti] + [wi])
                    new_hyp_scores[idx] = copy.copy(costs[idx])

                    new_hyp_states.append(copy.copy(next_state[ti]))
                    new_hyp_coverage.append(copy.copy(coverage[ti]))
                    new_hyp_ss.append(copy.copy(ss_prob[ti]))

                    if not return_attend:
                        new_hyp_ppps.append(hyp_ppps[ti] + [[next_prob0[ti][wi], next_prob[ti][wi]]])
                    else:
                        new_hyp_ppps.append(hyp_ppps[ti] + [(ss_prob[ti], alpha[ti])])

                # check the finished samples
                new_live_k   = 0
                hyp_samples  = []
                hyp_scores   = []
                hyp_states   = []
                hyp_coverage = []
                hyp_ppps     = []
                hyp_ss       = []

                for idx in xrange(len(new_hyp_samples)):
                    if (new_hyp_states[idx][-1] == 0) and (not fixlen):
                        sample.append(new_hyp_samples[idx])
                        ppp.append(new_hyp_ppps[idx])
                        score.append(new_hyp_scores[idx])
                        dead_k += 1
                    else:
                        new_live_k += 1
                        hyp_samples.append(new_hyp_samples[idx])
                        hyp_ppps.append(new_hyp_ppps[idx])
                        hyp_scores.append(new_hyp_scores[idx])
                        hyp_states.append(new_hyp_states[idx])
                        hyp_coverage.append(new_hyp_coverage[idx])
                        hyp_ss.append(new_hyp_ss[idx])

                hyp_scores = np.array(hyp_scores)
                live_k = new_live_k

                if new_live_k < 1:
                    break
                if dead_k >= k:
                    break

                next_word  = np.array([w[-1] for w in hyp_samples])
                next_state = np.array(hyp_states)
                coverage   = np.array(hyp_coverage)
                ss_prob    = np.array(hyp_ss)
                pass

        # end.
        if not stochastic:
            # dump every remaining one
            if live_k > 0:
                for idx in xrange(live_k):
                    sample.append(hyp_samples[idx])
                    ppp.append(hyp_ppps[idx])
                    score.append(hyp_scores[idx])

        return sample, score, ppp


class FnnDecoder(Model):
    def __init__(self, config, rng, prefix='fnndec'):
        """
        mode = RNN: use a RNN Decoder
        """
        super(FnnDecoder, self).__init__()
        self.config = config
        self.rng = rng
        self.prefix = prefix
        self.name = prefix

        """
        Create Dense Predictor.
        """

        self.Tr = Dense(self.config['dec_contxt_dim'],
                             self.config['dec_hidden_dim'],
                             activation='maxout2',
                             name='{}_Tr'.format(prefix))
        self._add(self.Tr)

        self.Pr = Dense(self.config['dec_hidden_dim'] / 2,
                             self.config['dec_voc_size'],
                             activation='softmax',
                             name='{}_Pr'.format(prefix))
        self._add(self.Pr)
        logger.info("FF decoder ok.")

    @staticmethod
    def _grab_prob(probs, X):
        assert probs.ndim == 3

        batch_size = probs.shape[0]
        max_len = probs.shape[1]
        vocab_size = probs.shape[2]

        probs = probs.reshape((batch_size * max_len, vocab_size))
        return probs[T.arange(batch_size * max_len), X.flatten(1)].reshape(X.shape)  # advanced indexing

    def build_decoder(self, target, context):
        """
        Build the Decoder Computational Graph
        """
        prob_dist = self.Pr(self.Tr(context[:, None, :]))
        log_prob  = T.sum(T.log(self._grab_prob(prob_dist, target) + err), axis=1)
        return log_prob

    def build_sampler(self):
        context   = T.matrix()
        prob_dist = self.Pr(self.Tr(context))
        next_sample = self.rng.multinomial(pvals=prob_dist).argmax(1)
        self.sample_next = theano.function([context], [prob_dist, next_sample], name='sample_next_{}'.format(self.prefix))
        logger.info('done')

    def get_sample(self, context, argmax=True):

        prob, sample = self.sample_next(context)
        if argmax:
            return prob[0].argmax()
        else:
            return sample[0]


########################################################################################################################
# Encoder-Decoder Models ::::
#
class RNNLM(Model):
    """
    RNN-LM, with context vector = 0.
    It is very similar with the implementation of VAE.
    """
    def __init__(self,
                 config, n_rng, rng,
                 mode='Evaluation'):
        super(RNNLM, self).__init__()

        self.config = config
        self.n_rng  = n_rng  # numpy random stream
        self.rng    = rng  # Theano random stream
        self.mode   = mode
        self.name   = 'rnnlm'

    def build_(self):
        logger.info("build the RNN-decoder")
        self.decoder = Decoder(self.config, self.rng, prefix='dec', mode=self.mode)

        # registration:
        self._add(self.decoder)

        # objectives and optimizers
        self.optimizer = optimizers.get('adadelta')

        # saved the initial memories
        if self.config['mode'] == 'NTM':
            self.memory    = initializations.get('glorot_uniform')(
                    (self.config['dec_memory_dim'], self.config['dec_memory_wdth']))

        logger.info("create the RECURRENT language model. ok")

    def compile_(self, mode='train', contrastive=False):
        # compile the computational graph.
        # INFO: the parameters.
        # mode: 'train'/ 'display'/ 'policy' / 'all'

        ps = 'params: {\n'
        for p in self.params:
            ps += '{0}: {1}\n'.format(p.name, p.eval().shape)
        ps += '}.'
        logger.info(ps)

        param_num = np.sum([np.prod(p.shape.eval()) for p in self.params])
        logger.info("total number of the parameters of the model: {}".format(param_num))

        if mode == 'train' or mode == 'all':
            if not contrastive:
                self.compile_train()
            else:
                self.compile_train_CE()

        if mode == 'display' or mode == 'all':
            self.compile_sample()

        if mode == 'inference' or mode == 'all':
            self.compile_inference()

    def compile_train(self):

        # questions (theano variables)
        inputs  = T.imatrix()  # padded input word sequence (for training)
        if self.config['mode']   == 'RNN':
            context = alloc_zeros_matrix(inputs.shape[0], self.config['dec_contxt_dim'])
        elif self.config['mode'] == 'NTM':
            context = T.repeat(self.memory[None, :, :], inputs.shape[0], axis=0)
        else:
            raise NotImplementedError

        # decoding.
        target  = inputs
        logPxz, logPPL = self.decoder.build_decoder(target, context)

        # reconstruction loss
        loss_rec = T.mean(-logPxz)
        loss_ppl = T.exp(T.mean(-logPPL))

        L1       = T.sum([T.sum(abs(w)) for w in self.params])
        loss     = loss_rec

        updates = self.optimizer.get_updates(self.params, loss)

        logger.info("compiling the compuational graph ::training function::")
        train_inputs = [inputs]

        self.train_ = theano.function(train_inputs,
                                      [loss_rec, loss_ppl],
                                      updates=updates,
                                      name='train_fun')
        logger.info("pre-training functions compile done.")

        # add monitoring:
        self.monitor['context'] = context
        self._monitoring()

        # compiling monitoring
        self.compile_monitoring(train_inputs)

    @abstractmethod
    def compile_train_CE(self):
        pass

    def compile_sample(self):
        # context vectors (as)
        self.decoder.build_sampler()
        logger.info("display functions compile done.")

    @abstractmethod
    def compile_inference(self):
        pass

    def default_context(self):
        if self.config['mode'] == 'RNN':
            return np.zeros(shape=(1, self.config['dec_contxt_dim']), dtype=theano.config.floatX)
        elif self.config['mode'] == 'NTM':
            memory = self.memory.get_value()
            memory = memory.reshape((1, memory.shape[0], memory.shape[1]))
            return memory

    def generate_(self, context=None, max_len=None, mode='display'):
        """
        :param action: action vector to guide the question.
                       If None, use a Gaussian to simulate the action.
        :return: question sentence in natural language.
        """
        # assert self.config['sample_stoch'], 'RNNLM sampling must be stochastic'
        # assert not self.config['sample_argmax'], 'RNNLM sampling cannot use argmax'

        if context is None:
            context = self.default_context()

        args = dict(k=self.config['sample_beam'],
                    maxlen=self.config['max_len'] if not max_len else max_len,
                    stochastic=self.config['sample_stoch'] if mode == 'display' else None,
                    argmax=self.config['sample_argmax'] if mode == 'display' else None)

        sample, score = self.decoder.get_sample(context, **args)
        if not args['stochastic']:
            score = score / np.array([len(s) for s in sample])
            sample = sample[score.argmin()]
            score = score.min()
        else:
            score /= float(len(sample))

        return sample, np.exp(score)


class AutoEncoder(RNNLM):
    """
    Regular Auto-Encoder: RNN Encoder/Decoder
    """

    def __init__(self,
                 config, n_rng, rng,
                 mode='Evaluation'):
        super(RNNLM, self).__init__()

        self.config = config
        self.n_rng  = n_rng  # numpy random stream
        self.rng    = rng  # Theano random stream
        self.mode   = mode
        self.name = 'vae'

    def build_(self):
        logger.info("build the RNN auto-encoder")
        self.encoder = Encoder(self.config, self.rng, prefix='enc')
        if self.config['shared_embed']:
            self.decoder = Decoder(self.config, self.rng, prefix='dec', embed=self.encoder.Embed)
        else:
            self.decoder = Decoder(self.config, self.rng, prefix='dec')

        """
        Build the Transformation
        """
        if self.config['nonlinear_A']:
            self.action_trans = Dense(
                self.config['enc_hidden_dim'],
                self.config['action_dim'],
                activation='tanh',
                name='action_transform'
            )
        else:
            assert self.config['enc_hidden_dim'] == self.config['action_dim'], \
                    'hidden dimension must match action dimension'
            self.action_trans = Identity(name='action_transform')

        if self.config['nonlinear_B']:
            self.context_trans = Dense(
                self.config['action_dim'],
                self.config['dec_contxt_dim'],
                activation='tanh',
                name='context_transform'
            )
        else:
            assert self.config['dec_contxt_dim'] == self.config['action_dim'], \
                    'action dimension must match context dimension'
            self.context_trans = Identity(name='context_transform')

        # registration
        self._add(self.action_trans)
        self._add(self.context_trans)
        self._add(self.encoder)
        self._add(self.decoder)

        # objectives and optimizers
        self.optimizer = optimizers.get(self.config['optimizer'], kwargs={'lr': self.config['lr']})

        logger.info("create Helmholtz RECURRENT neural network. ok")

    def compile_train(self, mode='train'):
        # questions (theano variables)
        inputs  = T.imatrix()  # padded input word sequence (for training)
        context = alloc_zeros_matrix(inputs.shape[0], self.config['dec_contxt_dim'])
        assert context.ndim == 2

        # decoding.
        target  = inputs
        logPxz, logPPL = self.decoder.build_decoder(target, context)

        # reconstruction loss
        loss_rec = T.mean(-logPxz)
        loss_ppl = T.exp(T.mean(-logPPL))

        L1       = T.sum([T.sum(abs(w)) for w in self.params])
        loss     = loss_rec

        updates = self.optimizer.get_updates(self.params, loss)

        logger.info("compiling the compuational graph ::training function::")
        train_inputs = [inputs]

        self.train_ = theano.function(train_inputs,
                                      [loss_rec, loss_ppl],
                                      updates=updates,
                                      name='train_fun')
        logger.info("pre-training functions compile done.")

        if mode == 'display' or mode == 'all':
            """
            build the sampler function here <:::>
            """
            # context vectors (as)
            self.decoder.build_sampler()
            logger.info("display functions compile done.")

        # add monitoring:
        self._monitoring()

        # compiling monitoring
        self.compile_monitoring(train_inputs)


class NRM(Model):
    """
    Neural Responding Machine
    A Encoder-Decoder based responding model.
    """
    def __init__(self,
                 config, n_rng, rng,
                 mode='Evaluation',
                 use_attention=False,
                 copynet=False,
                 identity=False):
        super(NRM, self).__init__()

        self.config   = config
        self.n_rng    = n_rng  # numpy random stream
        self.rng      = rng  # Theano random stream
        self.mode     = mode
        self.name     = 'nrm'
        self.attend   = use_attention
        self.copynet  = copynet
        self.identity = identity

    def build_(self, lr=None, iterations=None):
        logger.info("build the Neural Responding Machine")

        # encoder-decoder:: <<==>>
        self.encoder = Encoder(self.config, self.rng, prefix='enc', mode=self.mode)
        if not self.attend:
            self.decoder = Decoder(self.config, self.rng, prefix='dec', mode=self.mode)
        else:
            self.decoder = DecoderAtt(self.config, self.rng, prefix='dec', mode=self.mode,
                                      copynet=self.copynet, identity=self.identity)

        self._add(self.encoder)
        self._add(self.decoder)

        # objectives and optimizers
        if self.config['optimizer'] == 'adam':
            self.optimizer = optimizers.get(self.config['optimizer'],
                                         kwargs=dict(rng=self.rng,
                                                     save=False))
        else:
            self.optimizer = optimizers.get(self.config['optimizer'])
        if lr is not None:
            self.optimizer.lr.set_value(floatX(lr))
            self.optimizer.iterations.set_value(floatX(iterations))
        logger.info("build ok.")

    def compile_(self, mode='all', contrastive=False):
        # compile the computational graph.
        # INFO: the parameters.
        # mode: 'train'/ 'display'/ 'policy' / 'all'

        ps = 'params: {\n'
        for p in self.params:
            ps += '{0}: {1}\n'.format(p.name, p.eval().shape)
        ps += '}.'
        logger.info(ps)

        param_num = np.sum([np.prod(p.shape.eval()) for p in self.params])
        logger.info("total number of the parameters of the model: {}".format(param_num))

        if mode == 'train' or mode == 'all':
            self.compile_train()

        if mode == 'display' or mode == 'all':
            self.compile_sample()

        if mode == 'inference' or mode == 'all':
            self.compile_inference()

    def compile_train(self):

        # questions (theano variables)
        inputs    = T.imatrix()  # padded input word sequence (for training)
        target    = T.imatrix()  # padded target word sequence (for training)
        cc_matrix = T.tensor3()

        # encoding & decoding

        code, _, c_mask, _ = self.encoder.build_encoder(inputs, None, return_sequence=True, return_embed=True)
        # code: (nb_samples, max_len, contxt_dim)
        if 'explicit_loc' in self.config:
            if self.config['explicit_loc']:
                print 'use explicit location!!'
                max_len = code.shape[1]
                expLoc  = T.eye(max_len, self.config['encode_max_len'], dtype='float32')[None, :, :]
                expLoc  = T.repeat(expLoc, code.shape[0], axis=0)
                code    = T.concatenate([code, expLoc], axis=2)

        logPxz, logPPL     = self.decoder.build_decoder(target, cc_matrix,
                                                        code, c_mask)

        # responding loss
        loss_rec = T.mean(-logPxz)
        loss_ppl = T.exp(T.mean(-logPPL))
        loss     = loss_rec

        updates  = self.optimizer.get_updates(self.params, loss)

        logger.info("compiling the compuational graph ::training function::")
        train_inputs = [inputs, target, cc_matrix]

        self.train_ = theano.function(train_inputs,
                                      [loss_rec, loss_ppl],
                                      updates=updates,
                                      name='train_fun')
        self.train_guard = theano.function(train_inputs,
                                      [loss_rec, loss_ppl],
                                      updates=updates,
                                      name='train_fun',
                                      mode=NanGuardMode(nan_is_error=True, inf_is_error=True, big_is_error=True))
        logger.info("training functions compile done.")

        # # add monitoring:
        # self.monitor['context'] = context
        # self._monitoring()
        #
        # # compiling monitoring
        # self.compile_monitoring(train_inputs)

    def compile_sample(self):
        if not self.attend:
            self.encoder.compile_encoder(with_context=False)
        else:
            self.encoder.compile_encoder(with_context=False, return_sequence=True, return_embed=True)

        self.decoder.build_sampler()
        logger.info("sampling functions compile done.")

    def compile_inference(self):
        pass

    def generate_(self, inputs, mode='display', return_attend=False, return_all=False):
        # assert self.config['sample_stoch'], 'RNNLM sampling must be stochastic'
        # assert not self.config['sample_argmax'], 'RNNLM sampling cannot use argmax'

        args = dict(k=self.config['sample_beam'],
                    maxlen=self.config['max_len'],
                    stochastic=self.config['sample_stoch'] if mode == 'display' else None,
                    argmax=self.config['sample_argmax'] if mode == 'display' else None,
                    return_attend=return_attend)
        context, _, c_mask, _, Z, R = self.encoder.gtenc(inputs)
        # c_mask[0, 3] = c_mask[0, 3] * 0
        # L   = context.shape[1]
        # izz = np.concatenate([np.arange(3), np.asarray([1,2]), np.arange(3, L)])
        # context = context[:, izz, :]
        # c_mask  = c_mask[:, izz]
        # inputs  = inputs[:, izz]
        # context, _, c_mask, _ = self.encoder.encode(inputs)
        # import pylab as plt
        # # visualize_(plt.subplots(), Z[0][:, 300:], normal=False)
        # visualize_(plt.subplots(), context[0], normal=False)

        if 'explicit_loc' in self.config:
            if self.config['explicit_loc']:
                max_len = context.shape[1]
                expLoc  = np.eye(max_len, self.config['encode_max_len'], dtype='float32')[None, :, :]
                expLoc  = np.repeat(expLoc, context.shape[0], axis=0)
                context = np.concatenate([context, expLoc], axis=2)

        sample, score, ppp    = self.decoder.get_sample(context, c_mask, inputs, **args)
        if return_all:
            return sample, score, ppp

        if not args['stochastic']:
            score  = score / np.array([len(s) for s in sample])
            idz    = score.argmin()
            sample = sample[idz]
            score  = score.min()
            ppp    = ppp[idz]
        else:
            score /= float(len(sample))

        return sample, np.exp(score), ppp

    def evaluate_(self, inputs, outputs, idx2word, inputs_unk=None, encode=True):
        def cut_zero_yes(sample, idx2word, ppp=None, Lmax=None):
            if Lmax is None:
                Lmax = self.config['dec_voc_size']
            if ppp is None:
                if 0 not in sample:
                    return ['{}'.format(idx2word[w].encode('utf-8'))
                            if w < Lmax else '{}'.format(idx2word[inputs[w - Lmax]].encode('utf-8'))
                            for w in sample]

                return ['{}'.format(idx2word[w].encode('utf-8'))
                        if w < Lmax else '{}'.format(idx2word[inputs[w - Lmax]].encode('utf-8'))
                        for w in sample[:sample.index(0)]]
            else:
                if 0 not in sample:
                    return ['{0} ({1:1.1f})'.format(
                            idx2word[w].encode('utf-8'), p)
                            if w < Lmax
                            else '{0} ({1:1.1f})'.format(
                            idx2word[inputs[w - Lmax]].encode('utf-8'), p)
                            for w, p in zip(sample, ppp)]
                idz = sample.index(0)
                return ['{0} ({1:1.1f})'.format(
                        idx2word[w].encode('utf-8'), p)
                        if w < Lmax
                        else '{0} ({1:1.1f})'.format(
                        idx2word[inputs[w - Lmax]].encode('utf-8'), p)
                        for w, p in zip(sample[:idz], ppp[:idz])]

        def cut_zero_no(sample, idx2word, ppp=None, Lmax=None):
            if Lmax is None:
                Lmax = self.config['dec_voc_size']
            if ppp is None:
                if 0 not in sample:
                    return ['{}'.format(idx2word[w])
                            if w < Lmax else '{}'.format(idx2word[inputs[w - Lmax]].encode('utf-8'))
                            for w in sample]

                return ['{}'.format(idx2word[w])
                        if w < Lmax else '{}'.format(idx2word[inputs[w - Lmax]].encode('utf-8'))
                        for w in sample[:sample.index(0)]]
            else:
                if 0 not in sample:
                    return ['{0} ({1:1.1f})'.format(
                            idx2word[w], p)
                            if w < Lmax
                            else '{0} ({1:1.1f})'.format(
                            idx2word[inputs[w - Lmax]], p)
                            for w, p in zip(sample, ppp)]
                idz = sample.index(0)
                return ['{0} ({1:1.1f})'.format(
                        idx2word[w].encode('utf-8'), p)
                        if w < Lmax
                        else '{0} ({1:1.1f})'.format(
                        idx2word[inputs[w - Lmax]], p)
                        for w, p in zip(sample[:idz], ppp[:idz])]

        if inputs_unk is None:
            result, _, ppp = self.generate_(inputs[None, :])
        else:
            result, _, ppp = self.generate_(inputs_unk[None, :])

        if encode:
            cut_zero = cut_zero_yes
        else:
            cut_zero = cut_zero_no
        pp0, pp1 = [np.asarray(p) for p in zip(*ppp)]
        pp = (pp1 - pp0) / pp1
        # pp = (pp1 - pp0) / pp1
        print len(ppp)

        print '<Environment> [lr={0}][iter={1}]'.format(self.optimizer.lr.get_value(),
                                                        self.optimizer.iterations.get_value())

        a = '[SOURCE]: {}\n'.format(' '.join(cut_zero(inputs.tolist(),  idx2word, Lmax=len(idx2word))))
        b = '[TARGET]: {}\n'.format(' '.join(cut_zero(outputs.tolist(), idx2word, Lmax=len(idx2word))))
        c = '[DECODE]: {}\n'.format(' '.join(cut_zero(result, idx2word)))
        d = '[CpRate]: {}\n'.format(' '.join(cut_zero(result, idx2word, pp.tolist())))
        e = '[CpRate]: {}\n'.format(' '.join(cut_zero(result, idx2word, result)))
        print a
        print '{0} -> {1}'.format(len(a.split()), len(b.split()))

        if inputs_unk is not None:
            k = '[_INPUT]: {}\n'.format(' '.join(cut_zero(inputs_unk.tolist(),  idx2word, Lmax=len(idx2word))))
            print k
            a += k

        print b
        print c
        print d
        # print e
        a += b + c + d
        return a

    def analyse_(self, inputs, outputs, idx2word, inputs_unk=None, return_attend=False, name=None, display=False):
        def cut_zero(sample, idx2word, ppp=None, Lmax=None):
            if Lmax is None:
                Lmax = self.config['dec_voc_size']
            if ppp is None:
                if 0 not in sample:
                    return ['{}'.format(idx2word[w].encode('utf-8'))
                            if w < Lmax else '{}'.format(idx2word[inputs[w - Lmax]].encode('utf-8'))
                            for w in sample]

                return ['{}'.format(idx2word[w].encode('utf-8'))
                        if w < Lmax else '{}'.format(idx2word[inputs[w - Lmax]].encode('utf-8'))
                        for w in sample[:sample.index(0)]]
            else:
                if 0 not in sample:
                    return ['{0} ({1:1.1f})'.format(
                            idx2word[w].encode('utf-8'), p)
                            if w < Lmax
                            else '{0} ({1:1.1f})'.format(
                            idx2word[inputs[w - Lmax]].encode('utf-8'), p)
                            for w, p in zip(sample, ppp)]
                idz = sample.index(0)
                return ['{0} ({1:1.1f})'.format(
                        idx2word[w].encode('utf-8'), p)
                        if w < Lmax
                        else '{0} ({1:1.1f})'.format(
                        idx2word[inputs[w - Lmax]].encode('utf-8'), p)
                        for w, p in zip(sample[:idz], ppp[:idz])]

        if inputs_unk is None:
            result, _, ppp = self.generate_(inputs[None, :],
                                            return_attend=return_attend)
        else:
            result, _, ppp = self.generate_(inputs_unk[None, :],
                                            return_attend=return_attend)

        source = '{}'.format(' '.join(cut_zero(inputs.tolist(),  idx2word, Lmax=len(idx2word))))
        target = '{}'.format(' '.join(cut_zero(outputs.tolist(), idx2word, Lmax=len(idx2word))))
        decode = '{}'.format(' '.join(cut_zero(result, idx2word)))

        if display:
            print source
            print target
            print decode

            idz    = result.index(0)
            p1, p2 = [np.asarray(p) for p in zip(*ppp)]
            print p1.shape
            import pylab as plt
            # plt.rc('text', usetex=True)
            # plt.rc('font', family='serif')
            visualize_(plt.subplots(), 1 - p1[:idz, :].T, grid=True, name=name)
            visualize_(plt.subplots(), 1 - p2[:idz, :].T, name=name)

            # visualize_(plt.subplots(), 1 - np.mean(p2[:idz, :], axis=1, keepdims=True).T)
        return target == decode

    def analyse_cover(self, inputs, outputs, idx2word, inputs_unk=None, return_attend=False, name=None, display=False):
        def cut_zero(sample, idx2word, ppp=None, Lmax=None):
            if Lmax is None:
                Lmax = self.config['dec_voc_size']
            if ppp is None:
                if 0 not in sample:
                    return ['{}'.format(idx2word[w].encode('utf-8'))
                            if w < Lmax else '{}'.format(idx2word[inputs[w - Lmax]].encode('utf-8'))
                            for w in sample]

                return ['{}'.format(idx2word[w].encode('utf-8'))
                        if w < Lmax else '{}'.format(idx2word[inputs[w - Lmax]].encode('utf-8'))
                        for w in sample[:sample.index(0)]]
            else:
                if 0 not in sample:
                    return ['{0} ({1:1.1f})'.format(
                            idx2word[w].encode('utf-8'), p)
                            if w < Lmax
                            else '{0} ({1:1.1f})'.format(
                            idx2word[inputs[w - Lmax]].encode('utf-8'), p)
                            for w, p in zip(sample, ppp)]
                idz = sample.index(0)
                return ['{0} ({1:1.1f})'.format(
                        idx2word[w].encode('utf-8'), p)
                        if w < Lmax
                        else '{0} ({1:1.1f})'.format(
                        idx2word[inputs[w - Lmax]].encode('utf-8'), p)
                        for w, p in zip(sample[:idz], ppp[:idz])]

        if inputs_unk is None:
            results, _, ppp = self.generate_(inputs[None, :],
                                            return_attend=return_attend,
                                            return_all=True)
        else:
            results, _, ppp = self.generate_(inputs_unk[None, :],
                                            return_attend=return_attend,
                                            return_all=True)

        source = '{}'.format(' '.join(cut_zero(inputs.tolist(),  idx2word, Lmax=len(idx2word))))
        target = '{}'.format(' '.join(cut_zero(outputs.tolist(), idx2word, Lmax=len(idx2word))))
        # decode = '{}'.format(' '.join(cut_zero(result, idx2word)))

        score  = [target == '{}'.format(' '.join(cut_zero(result, idx2word))) for result in results]
        return max(score)
