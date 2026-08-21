from __future__ import annotations


EXTRACTION_SYSTEM_PROMPT = """Tu es un assistant d'extraction de données ESG.
Ta tâche est d'extraire **uniquement la valeur demandée** depuis un contexte de pages d'un PDF d'entreprise.
Règles:
- Ne raisonne pas, ne calcule pas, ne somme pas, ne déduis pas.
- Si plusieurs nombres, choisis celui avec ‘Total’.
- Tu dois toujours remplir content : ne réponds jamais vide.
- Réponds sur une seule ligne STRICTEMENT au format JSON valide: {"valeur": "..."}
- Le champ "valeur" doit UNIQUEMENT contenir la donnée demandée (ex: un nombre + unité si applicable), sans commentaire.
- Si la valeur est absente/non publiée, réponds: {"valeur": "NA"}
- Privilégie TOUJOURS l'année en cours ou la plus récente disponible pour extraire la valeur demandée (par exemple 2024 si le document est 2024/2025), ne privilégie JAMAIS l'année de référence ou l'année de base.
- Si plusieurs chiffres existent (ex: brut vs net), choisis le total consolidé le plus pertinent et le plus récent.
- Respecte l'unité cible si possible; sinon, renvoie l'unité telle que publiée.
"""


def build_user_prompt(metric: str, unite: str) -> str:
    """Construit le prompt utilisateur (instructions) envoyé au LLM.

    Le contexte PDF est injecté séparément (section CONTEXT) pour faciliter l'audit.
    """
    return f"""Extrait du CONTEXT la métrique suivante :
Métrique: {metric}
Unité cible: {unite}

Réponds IMPERATIVEMENT AU FORMAT JSON : {{"valeur": "<valeur_seule>", "unité": "<unité_seule>", "paragraphe": "<ligne_de_text_ou_se_trouve_la_valeur>"}}
Si la valeur est multiple respecte le format "label1:valeur1/label2:valeur2/label3:valeur3 ..." ou "valeur1/valeur2/valeur3 ..." (ex1. nombre de salariés par genre : homme:10/femme:100, ex2: Les pays dans lesquels l'entreprise est implantée : "pays1/pays2/pays3 ..." ) 
Si la valeur est manquante dans le CONTEXT renvoit : {{"valeur": "NA", "unité":"NA", "paragraphe": "NA"}}.
"""
