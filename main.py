import difflib
import editdistance
import math
import numpy as np
import re
import spacy
from spacy.language import Language
import string
import torch
from nltk.tokenize import sent_tokenize
from tqdm import tqdm
from transformers import BertConfig, BertForSequenceClassification, BertTokenizer, BertForMaskedLM
from transformers import glue_convert_examples_to_features, logging
from transformers.data.processors.utils import InputExample
from wmd import WMD

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
""" Processing """


def preprocess_candidates(candidates):
    for i in range(len(candidates)):
        candidates[i] = candidates[i].strip()
        candidates[i] = '. '.join(candidates[i].split('\n\n'))
        candidates[i] = '. '.join(candidates[i].split('\n'))
        candidates[i] = '.'.join(candidates[i].split('..'))
        candidates[i] = '. '.join(candidates[i].split('.'))
        candidates[i] = '. '.join(candidates[i].split('. . '))
        candidates[i] = '. '.join(candidates[i].split('.  . '))
        while len(candidates[i].split('  ')) > 1:
            candidates[i] = ' '.join(candidates[i].split('  '))
        myre = re.search(r'(\d+)\. (\d+)', candidates[i])
        while myre:
            candidates[i] = 'UNK'.join(candidates[i].split(myre.group()))
            myre = re.search(r'(\d+)\. (\d+)', candidates[i])
        candidates[i] = candidates[i].strip()
    processed_candidates = []
    for candidate_i in candidates:
        sentences = sent_tokenize(candidate_i)
        out_i = []
        for sentence_i in sentences:
            if len(
                    sentence_i.translate(
                        str.maketrans('', '', string.punctuation)).split()
            ) > 1:  # More than one word.
                out_i.append(sentence_i)
        processed_candidates.append(out_i)
    return processed_candidates


""" Scores Calculation """


def get_lm_score(sentences):

    def score_sentence(sentence, tokenizer, model):
        # if len(sentence.strip().split()) <= 1:
        #     return 10000
        tokenize_input = tokenizer.tokenize(sentence)
        if len(tokenize_input) > 510:
            tokenize_input = tokenize_input[:510]
        input_ids = torch.tensor(
            tokenizer.encode(tokenize_input)).unsqueeze(0).to(device)
        with torch.no_grad():
            loss = model(input_ids, labels=input_ids)[0]
        return math.exp(loss.item())

    model_name = 'bert-base-cased'
    model = BertForMaskedLM.from_pretrained(model_name).to(device)
    model.eval()
    tokenizer = BertTokenizer.from_pretrained(model_name)
    lm_score = []
    for sentence in tqdm(sentences):
        if len(sentence) == 0:
            lm_score.append(0.0)
            continue
        score_i = 0.0
        for x in sentence:
            score_i += score_sentence(x, tokenizer, model)
        score_i /= len(sentence)
        lm_score.append(score_i)
    return lm_score


def get_cola_score(sentences):

    def load_pretrained_cola_model(model_name,
                                   saved_pretrained_CoLA_model_dir):
        config_class, model_class, tokenizer_class = (
            BertConfig, BertForSequenceClassification, BertTokenizer)
        config = config_class.from_pretrained(saved_pretrained_CoLA_model_dir,
                                              num_labels=2,
                                              finetuning_task='CoLA')
        tokenizer = tokenizer_class.from_pretrained(
            saved_pretrained_CoLA_model_dir, do_lower_case=0)
        model = model_class.from_pretrained(
            saved_pretrained_CoLA_model_dir,
            from_tf=bool('.ckpt' in model_name),
            config=config).to(device)
        model.eval()
        return tokenizer, model

    def evaluate_cola(model, candidates, tokenizer, model_name):

        def load_and_cache_examples(candidates, tokenizer):
            max_length = 128
            examples = [
                InputExample(guid=str(i), text_a=x)
                for i, x in enumerate(candidates)
            ]
            features = glue_convert_examples_to_features(
                examples,
                tokenizer,
                label_list=["0", "1"],
                max_length=max_length,
                output_mode="classification")
            # Convert to Tensors and build dataset
            all_input_ids = torch.tensor([f.input_ids for f in features],
                                         dtype=torch.long)
            all_attention_mask = torch.tensor(
                [f.attention_mask for f in features], dtype=torch.long)
            all_labels = torch.tensor([0 for f in features], dtype=torch.long)
            all_token_type_ids = torch.tensor([[0.0] * max_length
                                               for f in features],
                                              dtype=torch.long)
            dataset = torch.utils.data.TensorDataset(all_input_ids,
                                                     all_attention_mask,
                                                     all_token_type_ids,
                                                     all_labels)
            return dataset

        eval_dataset = load_and_cache_examples(candidates, tokenizer)
        eval_dataloader = torch.utils.data.DataLoader(
            eval_dataset,
            sampler=torch.utils.data.SequentialSampler(eval_dataset),
            batch_size=max(1, torch.cuda.device_count()))
        preds = None
        for batch in tqdm(eval_dataloader, desc="Evaluating"):
            model.eval()
            batch = tuple(t.to(device) for t in batch)

            with torch.no_grad():
                inputs = {
                    'input_ids': batch[0],
                    'attention_mask': batch[1],
                    'labels': batch[3]
                }
                if model_name.split('-')[0] != 'distilbert':
                    inputs['token_type_ids'] = batch[2] if model_name.split(
                        '-'
                    )[0] in [
                        'bert', 'xlnet'
                    ] else None  # XLM, DistilBERT and RoBERTa don't use segment_ids
                outputs = model(**inputs)
                tmp_eval_loss, logits = outputs[:2]

            if preds is None:
                preds = logits.detach().cpu().numpy()
            else:
                preds = np.append(preds, logits.detach().cpu().numpy(), axis=0)
        return preds[:, 1].tolist()

    def convert_sentence_score_to_paragraph_score(sentence_score, sent_length):
        paragraph_score = []
        pointer = 0
        for i in sent_length:
            if i == 0:
                paragraph_score.append(0.0)
                continue
            temp_a = sentence_score[pointer:pointer + i]
            paragraph_score.append(sum(temp_a) / len(temp_a))
            pointer += i
        return paragraph_score

    model_name = 'bert-base-cased'
    saved_pretrained_CoLA_model_dir = './cola_model/' + model_name + '/'
    tokenizer, model = load_pretrained_cola_model(
        model_name, saved_pretrained_CoLA_model_dir)
    candidates = [y for x in sentences for y in x]
    sent_length = [len(x) for x in sentences]
    cola_score = evaluate_cola(model, candidates, tokenizer, model_name)
    cola_score = convert_sentence_score_to_paragraph_score(
        cola_score, sent_length)
    return cola_score


def get_grammaticality_score(processed_candidates):
    lm_score = get_lm_score(processed_candidates)
    cola_score = get_cola_score(processed_candidates)
    grammaticality_score = [
        1.0 * math.exp(-0.5 * x) + 1.0 * y
        for x, y in zip(lm_score, cola_score)
    ]
    grammaticality_score = [
        max(0, x / 8.0 + 0.5) for x in grammaticality_score
    ]  # re-scale
    return grammaticality_score


def get_redundancy_score(all_summary):

    def if_two_sentence_redundant(a, b):
        """ Determine whether there is redundancy between two sentences. """
        if a == b:
            return 4
        if (a in b) or (b in a):
            return 4
        flag_num = 0
        a_split = a.split()
        b_split = b.split()
        if max(len(a_split), len(b_split)) >= 5:
            longest_common_substring = difflib.SequenceMatcher(
                None, a, b).find_longest_match(0, len(a), 0, len(b))
            LCS_string_length = longest_common_substring.size
            if LCS_string_length > 0.8 * min(len(a), len(b)):
                flag_num += 1
            LCS_word_length = len(a[longest_common_substring[0]:(
                longest_common_substring[0] +
                LCS_string_length)].strip().split())
            if LCS_word_length > 0.8 * min(len(a_split), len(b_split)):
                flag_num += 1
            edit_distance = editdistance.eval(a, b)
            if edit_distance < 0.6 * max(
                    len(a), len(b)
            ):  # Number of modifications from the longer sentence is too small.
                flag_num += 1
            number_of_common_word = len([x for x in a_split if x in b_split])
            if number_of_common_word > 0.8 * min(len(a_split), len(b_split)):
                flag_num += 1
        return flag_num

    redundancy_score = [0.0 for x in range(len(all_summary))]
    for i in range(len(all_summary)):
        flag = 0
        summary = all_summary[i]
        if len(summary) == 1:
            continue
        for j in range(len(summary) - 1):  # for pairwise redundancy
            for k in range(j + 1, len(summary)):
                flag += if_two_sentence_redundant(summary[j].strip(),
                                                  summary[k].strip())
        redundancy_score[i] += -0.1 * flag
    return redundancy_score


@Language.component("simhook")
def SimilarityHook(doc):
    return WMD.SpacySimilarityHook(doc)


def get_focus_score(all_summary):

    def compute_sentence_similarity():
        nlp = spacy.load('en_core_web_md')
        nlp.add_pipe('simhook', last=True)
        all_score = []
        for i in range(len(all_summary)):
            if len(all_summary[i]) == 1:
                all_score.append([1.0])
                continue
            score = []
            for j in range(1, len(all_summary[i])):
                doc1 = nlp(all_summary[i][j - 1])
                doc2 = nlp(all_summary[i][j])
                try:
                    score.append(1.0 /
                                 (1.0 + math.exp(-doc1.similarity(doc2) + 7)))
                except:
                    score.append(1.0)
            all_score.append(score)
        return all_score

    all_score = compute_sentence_similarity()
    focus_score = [0.0 for x in range(len(all_summary))]
    for i in range(len(all_score)):
        if len(all_score[i]) == 0:
            continue
        if min(all_score[i]) < 0.05:
            focus_score[i] -= 0.1
    return focus_score


def get_gruen(candidates):
    processed_candidates = preprocess_candidates(candidates)
    grammaticality_score = get_grammaticality_score(processed_candidates)
    redundancy_score = get_redundancy_score(processed_candidates)
    focus_score = get_focus_score(processed_candidates)
    # We do not release the code for the coherence score calculation due to efficiency reasons. The GRUEN score are fairly reliable to use without adding the coherence score too.
    # For those who are interested in the coherence calculation, please email zhuw0006@e.ntu.edu.sg for code.
    # coherence_score = get_coherence_score(processed_candidates)
    
    gruen_score = [
        min(1, max(0, sum(i)))
        for i in zip(grammaticality_score, redundancy_score, focus_score)
    ]
    return gruen_score


if __name__ == "__main__":
    logging.set_verbosity_error()
    candidates = [
        "All I need is faith to believe it",
        "I can feel my heart is beating faster",
        "'cause I'm so selfishly in love with you",
        "All I see is this big bright world",
        "I dont't think you are worth waiting with"
    ]
    gruen_score = get_gruen(candidates)
    print(
        sorted(list(zip(candidates, gruen_score)),
               key=lambda x: x[1],
               reverse=True))
