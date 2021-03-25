#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec 14 12:54:11 2020

@author: qwang
"""

#%% Predict
import spacy
nlp = spacy.load('en_core_sci_sm')
import tensorflow as tf
import tensorflow_addons as tfa
from model import BiLSTM, CRF, BiLSTM_CRF

def pred_one(text, word2idx, idx2tag, model):
    '''
    Return
        tup: list of tuples (token, tag)
    '''
    tokens = [t.text for t in nlp(text)]
    seqs = []
    for word in tokens:
        if word in word2idx:
            idx = word2idx[word]
        elif word.lower() in word2idx:
            idx = word2idx[word.lower()]
        else:
            idx = word2idx['<unk>']
        seqs.append(idx)
        
    seqs = tf.convert_to_tensor(seqs, dtype=tf.int32)  # [seq_len]
    seqs = tf.expand_dims(seqs, 0)  # [batch_size=1, seq_len]
       
    if isinstance(model, BiLSTM):   
        logits = model(seqs)  # [1, seq_len, num_tags] 
        probs = tf.nn.softmax(logits, axis=2)  # [1, seq_len, num_tags]
        preds = tf.argmax(probs, axis=2)  # [1, seq_len]
        
    if isinstance(model, (CRF, BiLSTM_CRF)):
        logits, _ = model(seqs)  # [1, seq_len, num_tags] 
        logit = tf.squeeze(logits, axis = 0)  # [seq_len, num_tags]
        viterbi, _ = tfa.text.viterbi_decode(logit, model.trans_pars)  # [seq_len]      
        # viterbi, _ = tfa.text.viterbi_decode(logit[:text_len], model.transition_params)  # [text_len]
        preds = tf.convert_to_tensor(viterbi, dtype = tf.int32)  # [seq_len]  
        preds = tf.expand_dims(preds, 0)  # [1, seq_len]

    tags = [idx2tag[idx] for idx in preds.numpy()[0].tolist()]
    
    tup = []
    for token, tag in zip(tokens, tags):
        tup.append((token, tag))
    return tup

#%%
# text = '''Talks over a post-Brexit trade agreement will resume later, after the UK and EU agreed to "go the extra mile" in search of a breakthrough.'''
# print(pred_one(text, word2idx, idx2tag, model))

#%%
import torch

from transformers import BertTokenizerFast, BertForTokenClassification
from transformers import DistilBertTokenizerFast, DistilBertForTokenClassification
from bert.bert_model import BERT_CRF, BERT_LSTM_CRF, Distil_CRF

  
def pred_one_bert(text, mod, pre_wgts, pth_path, idx2tag):
    '''
    Return
        tup: list of tuples (token, tag)
    '''
    n_tags = len(idx2tag)
    ## Tokenization
    pre_wgts = 'distilbert-base-uncased' if pre_wgts == 'distil' else pre_wgts
    pre_wgts = 'bert-base-uncased' if pre_wgts == 'base' else pre_wgts
    pre_wgts = 'dmis-lab/biobert-v1.1' if pre_wgts == 'biobert' else pre_wgts
    pre_wgts = 'microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract' if pre_wgts == 'pubmed-abs' else pre_wgts
    pre_wgts = 'microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext' if pre_wgts == 'pubmed-full' else pre_wgts
    if pre_wgts == 'distilbert-base-uncased':
        tokenizer = DistilBertTokenizerFast.from_pretrained(pre_wgts, num_labels=n_tags) 
    else:
        tokenizer = BertTokenizerFast.from_pretrained(pre_wgts, num_labels=n_tags) 
      
    inputs = tokenizer([text], is_split_into_words=True, return_offsets_mapping=True, padding=False, truncation=True)
    inputs = {key: torch.tensor(value) for key, value in inputs.items()} 

    ## Load model
    if mod == 'bert':
        model = BertForTokenClassification.from_pretrained(pre_wgts, num_labels=n_tags) 
    if mod == 'bert_crf':
        model = BERT_CRF.from_pretrained(pre_wgts, num_labels=n_tags)
    if mod == 'bert_lstm_crf':
        model = BERT_LSTM_CRF.from_pretrained(pre_wgts, num_labels=n_tags)
    if mod == 'distil':
        model = DistilBertForTokenClassification.from_pretrained(pre_wgts, num_labels=n_tags)
    if mod == 'distil_crf':
        model = Distil_CRF.from_pretrained(pre_wgts, num_labels=n_tags)
    # Load checkpoint
    checkpoint = torch.load(pth_path, map_location=torch.device('cpu'))
    model.load_state_dict(checkpoint['state_dict'], strict=False)
    model.cpu()
    model.eval()
    
    ## Run model
    if mod in ['bert', 'distil']:
        outputs = model(inputs['input_ids'].unsqueeze(0), inputs['attention_mask'].unsqueeze(0)) 
        logits = outputs[0].squeeze(0)  # [seq_len, n_tags] 
        preds = torch.argmax(logits, dim=1)  # [seq_len]   
        preds = preds.numpy().tolist()[1:-1]  # len=seq_len-2, remove cls/sep token
    else:
        preds = model(inputs['input_ids'].unsqueeze(0), inputs['attention_mask'].unsqueeze(0)) 
        preds = preds[0]
        
    ids = inputs['input_ids'][1:-1]
    tokens = tokenizer.convert_ids_to_tokens(ids)
    tags = [idx2tag[idx] for idx in preds]
    
    # Record span start/end idxs
    sidxs, eidxs = [], []
    for i in range(len(tags)):
        if tags[0] != 'O':
            sidxs.append(0)
            if tags[1] == 'O':
                eidxs.append(0)     
                
        if i > 0 and i < len(tags)-1 and tags[i] != 'O':
            if tags[i-1] == 'O' and tags[i] != 'O':
                sidxs.append(i)
            if tags[i+1] == 'O' and tags[i] != 'O':
                eidxs.append(i)
        
        if tags[len(tags)-1] != 'O':
            sidxs.append(len(tags)-1)
            eidxs.append(len(tags)-1)

    tup = []
    for si, ei in zip(sidxs, eidxs):
        ent_tokens = tokens[si: ei+1]
        ent_tags = tags[si: ei+1]
        
        # ent_tags may include multiple type of tags
        ents = [t.split('-')[1] for t in ent_tags]
        ents_set = list(set(ents))        
        for ent in ents_set:
            indices = [idx for idx, t in enumerate(ent_tags) if t.split('-')[1] == ent]
            sub = [ent_tokens[ic] for ic in indices]
            sub_text = tokenizer.decode(tokenizer.convert_tokens_to_ids(sub))
            tup.append((ent, sub_text))
            
    return tup



#%% Convert tuple to entity dictionary and deduplication
from collections import defaultdict

def tup2dict(tup):
    ent_dict = defaultdict(list)
    for k, *v in tup:
        ent_dict[k].append(v[0])
    # Deduplicate
    for k, v in ent_dict.items():
        ent_dict[k] = list(set(v))
        
    return ent_dict
        
#%%
idx2tag = {0: 'B-Intervention',
 1: 'B-Species',
 2: 'I-Strain',
 3: 'B-Strain',
 4: 'I-Comparator',
 5: 'I-Outcome',
 6: 'B-Induction',
 7: 'O',
 8: 'B-Outcome',
 9: 'I-Intervention',
 10: 'B-Comparator',
 11: 'I-Induction',
 12: 'I-Species'}

mod = 'bert_crf'

pre_wgts = 'pubmed-full'
pth_path = '/home/qwang/pre-pico/exp/bert_crf/bc0_full/best.pth.tar'
text = '''In the present study, we examined the time-dependent changes of calbindin D-28k (CB) protein expression in the mouse hippocampus after a systemic administration of 1 mg/kg LPS. CB immunoreactivity was markedly increased in pyramidal cells of the hippocampal CA1/2 regions and in granule cells of the dentate gyrus from 3 hr to 48 hr after LPS treatment. At this point in time, CB protein level was also significantly increased in the mouse hippocampus. Thereafter, CB protein expression was decreased at 96 hr after LPS treatment.'''
text = '''The results of this study show increased production of IL‐2 and the inflammatory cytokines IL‐6, IL‐17 and TNF‐α by spleen cells of lesion‐bearing mice that were treated with PD‐1 antibody for 1 week compared to cytokine production by spleen cells of lesion‐bearing mice treated with control antibody. Production of IFN‐γ increased at 3 weeks of PD‐1 antibody treatment, although production of the other Th1 and inflammatory mediators declined. By 5 weeks, levels of these cytokines declined for both control and PD‐1 antibody‐treated mice. Flow cytometric analysis for IFN‐γ‐expressing cells showed shifts in CD4+ cells expressing IFN‐γ consistent with the changes in cytokine secretion. Whether or not treatment generated reactivity to lesions or HNSCC was determined. Spleen cells from PD‐1 antibody‐treated mice were stimulated by lysates of premalignant lesion and HNSCC tongue tissues to produce increased levels of Th1 and select inflammatory cytokines early in the course of PD‐1 antibody treatment. However, with continued treatment, reactivity to lesion and HNSCC lysates declined. Analysis of clinical response to treatment suggested an early delay in lesion progression but, with continued treatment, lesions in PD‐1 antibody‐treated mice progressed to the same degree as in control antibody‐treated mice'''

tup = pred_one_bert(text, mod, pre_wgts, pth_path, idx2tag)
print(tup2dict(tup))