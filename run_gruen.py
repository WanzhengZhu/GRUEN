import sys
from main import get_gruen
from transformers import glue_convert_examples_to_features, logging
import csv



def get_sentences(filename):
    with open(filename, 'r') as f:
        lines = f.readlines()
        return [l.replace('\n', '') for l in lines]

def write_results(filename, sentences, greun):
   with open(filename, mode='w', newline='') as f:
    writer = csv.writer(f) 
    writer.writerow(["Sentence", "Gruen Score"])
    for s, gr in zip(sentences, gruen_score):
            writer.writerow([s, gr])

if __name__ == "__main__":
    logging.set_verbosity_error()
    if len(sys.argv) != 3: 
        print(f"Usage: python run_gruen.py <file with list of phrases> <output_file>")
        sys.exit(-1)
    file_with_phrases = sys.argv[1]
    gruen_output_file = sys.argv[2]

    sentences = get_sentences(file_with_phrases)
    gruen_score = get_gruen(sentences)

    write_results(gruen_output_file, sentences, gruen_score)


    
    
    # gruen_score = get_gruen(candidates)