#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Dec 30 13:58:11 2020

@author: qwang
"""

import numpy as np
from tqdm import tqdm

import torch
import torch.nn as nn
import torch.nn.functional as F
import transformers

import bert_utils


#%% Train
def train_fn(model, data_loader, idx2tag, optimizer, scheduler, tokenizer, clip, accum_step, device):
    
    batch_loss = 0
    len_iter = len(data_loader)
    
    model.train()
    optimizer.zero_grad()
    
    epoch_preds, epoch_trues = [], []
    with tqdm(total=len_iter) as progress_bar:      
        for j, batch in enumerate(data_loader):                      
            
            input_ids = batch[0].to(device)  # [batch_size, seq_len]
            attn_mask = batch[1].to(device)  # [batch_size, seq_len]
            tags = batch[2].to(device)  # [batch_size, seq_len]
            true_lens = batch[3]  # [batch_size]
            word_ids = batch[4]   # [batch_size, seq_len]
        
            # preds_cut, log_likelihood = model(input_ids, attention_mask = attn_mask, labels = tags)  
            preds_cut, probs_cut, mask_cut, log_likelihood = model(input_ids, attention_mask = attn_mask, labels = tags) 
            # preds_cut = crf.decode(probs_cut, mask=mask_cut)

            loss = -1 * log_likelihood                          
            batch_loss += loss.item() 

            loss = loss / accum_step  # loss gradients are accumulated by loss.backward() so we need to ave accumulated loss gradients
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), clip)  # prevent exploding gradients               
            # Gradient accumulation    
            if (j+1) % accum_step == 0:
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
                            
            for sin_preds, sin_tags, sin_lens, sin_wids in zip(preds_cut, tags, true_lens, word_ids):
                sin_wids = sin_wids[1:sin_lens+1]
                sin_tags = sin_tags[1:sin_lens+1] # list of lists (1st/last tag is -100 so need to move one step)
                
                pre_wid = None
                sin_preds_new, sin_tags_new = [], []
                for p, t, wid in zip(sin_preds, sin_tags, sin_wids):
                    if wid != pre_wid:
                        sin_preds_new.append(p)
                        sin_tags_new.append(t.tolist())
                    pre_wid = wid
                epoch_preds.append(sin_preds_new)   # list of lists                 
                epoch_trues.append(sin_tags_new)  

            progress_bar.update(1)
    
    # Convert epoch_idxs to epoch_tags
    epoch_tag_preds = bert_utils.epoch_idx2tag(epoch_preds, idx2tag)
    epoch_tag_trues = bert_utils.epoch_idx2tag(epoch_trues, idx2tag)
    # Calculate metrics for whole epoch
    scores = bert_utils.scores(epoch_tag_trues, epoch_tag_preds)        
    scores['loss'] = batch_loss / len_iter
       
    return scores      


#%% Evaluate
def valid_fn(model, data_loader, idx2tag, tokenizer, device):
    
    batch_loss = 0
    len_iter = len(data_loader)
    
    model.eval()
    
    epoch_preds, epoch_trues = [], []
    with torch.no_grad():
        with tqdm(total=len_iter) as progress_bar:      
            for j, batch in enumerate(data_loader):                      
                
                input_ids = batch[0].to(device)  # [batch_size, seq_len]
                attn_mask = batch[1].to(device)  # [batch_size, seq_len]
                tags = batch[2].to(device)  # [batch_size, seq_len]
                true_lens = batch[3]  # [batch_size]
                word_ids = batch[4]  # [batch_size, seq_len]
    
                # preds_cut, log_likelihood = model(input_ids, attention_mask = attn_mask, labels = tags)   
                # preds: list of lists. each element is a tag seq with true_len (unpad & -100 removed) for one sample    
                preds_cut, probs_cut, mask_cut, log_likelihood = model(input_ids, attention_mask = attn_mask, labels = tags) 
                # preds_cut = crf.decode(probs_cut, mask=mask_cut)
                        
                loss = -1 * log_likelihood 
                batch_loss += loss.item()       
                
                for sin_preds, sin_tags, sin_lens, sin_wids in zip(preds_cut, tags, true_lens, word_ids):
                    sin_wids = sin_wids[1:sin_lens+1]
                    sin_tags = sin_tags[1:sin_lens+1] # list of lists (1st/last tag is -100 so need to move one step)
                    
                    pre_wid = None
                    sin_preds_new, sin_tags_new = [], []
                    for p, t, wid in zip(sin_preds, sin_tags, sin_wids):
                        if wid != pre_wid:
                            sin_preds_new.append(p)
                            sin_tags_new.append(t.tolist())
                        pre_wid = wid
                    epoch_preds.append(sin_preds_new)   # list of lists                 
                    epoch_trues.append(sin_tags_new)  
                progress_bar.update(1)         

    # Convert epoch_idxs to epoch_tags
    epoch_tag_preds = bert_utils.epoch_idx2tag(epoch_preds, idx2tag)
    epoch_tag_trues = bert_utils.epoch_idx2tag(epoch_trues, idx2tag)
    # Calculate metrics for whole epoch
    scores = bert_utils.scores(epoch_tag_trues, epoch_tag_preds)        
    scores['loss'] = batch_loss / len_iter

    return scores

