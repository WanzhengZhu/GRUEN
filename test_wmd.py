import spacy

import wmd
from spacy.language import Language
from spacy.tokens.doc import Doc



@Language.component("simhook")
def SimilarityHook(doc):
    doc.user_hooks['similarity'] = wmd.WMD.SpacySimilarityHook(doc).compute_similarity

    # return WMD.SpacySimilarityHook(doc)
    return doc

def main():
    nlp: Language = spacy.load('en_core_web_md')
    nlp.add_pipe('simhook', last=True)
    print(nlp.pipe_names)

    wmd_instance = wmd.WMD.SpacySimilarityHook(nlp)

    doc1: Doc = nlp("Politician speaks to the media in Illinois.")
    doc2: Doc = nlp("The president greets the press in Chicago.")

    print(doc1.similarity(doc2))
    print(wmd_instance.compute_similarity(doc1, doc2))


if __name__ == '__main__':
    main()
