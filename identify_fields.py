# from sklearn.feature_extraction.text import TfidfVectorizer
import spacy

# 1. Named Entity Recognition (NER)
def perform_named_entity_recognition(text):

    """
    Extract and classify named entities from text using spaCy
    """
    # Download and load English language model
    nlp = spacy.load("es_core_news_sm")
    
    # Process the text
    doc = nlp(text)
    
    # Extract named entities
    
    entities = {}
    for ent in doc.ents:
        if ent.label_ not in entities:
            entities[ent.label_] = []
        entities[ent.label_].append(ent.text)
    
    return entities

# Example usage
sample_text = "la amo kon todo el Kevin Astorga corason de mi alma Mexico "
print(perform_named_entity_recognition(sample_text))