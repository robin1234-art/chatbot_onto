"""Interface en ligne de commande du chatbot ontologique.

Usage :
    # Question unique, réponse puis sortie (utile en script / non-interactif)
    python -m chatbot.cli "Quels lauréats du Nobel de chimie ont étudié à Cambridge ?"

    # Mode interactif : boucle de questions tant qu'aucune question n'est fournie
    python -m chatbot.cli
"""

import argparse
import logging
from datetime import date

from .config import FUZZY_SUGGEST_THRESHOLD
from .dates import annotate_dates
from .entity_matcher import Match
from .graph_qa import build_chain
from .llm import get_llm
from .resolver import QuestionResolver, Resolution, Status, mentioned_iris


def _input(prompt: str) -> str:
    """input() qui renvoie une chaîne vide si l'entrée standard est fermée."""
    try:
        return input(prompt).strip().lower()
    except EOFError:
        print()
        return ""


def choose_entity(resolution: Resolution) -> Match | None:
    """Demande à l'utilisateur quelle entité il désignait.

    Renvoie l'individu retenu, ou None pour garder sa formulation.
    """
    text = resolution.mention.text
    candidates = resolution.candidates

    if resolution.status is Status.SUGGESTION:
        match = candidates[0]
        answer = _input(
            f'Vouliez-vous dire "{match.label}" ({match.description}) au lieu de "{text}" ? [O/n] '
        )
        return match if answer in ("", "o", "oui", "y", "yes") else None

    if resolution.status is Status.AMBIGUOUS:
        print(f'"{text}" peut désigner plusieurs entités :')
    else:
        print(f'Aucune entité ne correspond à "{text}". Entités proches du même type :')
    for i, match in enumerate(candidates, start=1):
        print(f"  {i}. {match.label} ({match.description})")
    print(f'  0. Garder "{text}"')

    while True:
        answer = _input("Votre choix [0] : ")
        if answer in ("", "0"):
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]
        print(f"Choix invalide : entrez un nombre entre 0 et {len(candidates)}.")


def ask(chain, resolver: QuestionResolver, question: str) -> None:
    reformulated = annotate_dates(resolver.reformulate(question, choose_entity), date.today())
    if reformulated != question:
        print(f"\nQuestion reformulée : {reformulated}")
    chain.graph.mentioned = mentioned_iris(reformulated)
    try:
        result = chain.invoke({"query": reformulated})
    except Exception as error:  # requête SPARQL invalide, erreur du LLM...
        print(f"\nÉchec : {error}\n")
        return
    print(f"\nSPARQL généré :\n{result.get('sparql_query')}")
    print(f"\nRéponse : {result.get('result')}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chatbot ontologique (Text-to-SPARQL)")
    parser.add_argument(
        "question",
        nargs="?",
        default=None,
        help="Question à poser. Si omise, lance une boucle interactive.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Masque les logs verbeux de la chaîne LangChain.",
    )
    args = parser.parse_args()

    if not args.quiet:
        # Trace les corrections appliquées d'office (entités, types des littéraux).
        chatbot_logger = logging.getLogger("chatbot")
        chatbot_logger.setLevel(logging.INFO)
        chatbot_logger.addHandler(logging.StreamHandler())

    chain = build_chain(verbose=not args.quiet)
    resolver = QuestionResolver.from_graph(chain.graph.graph, get_llm(), FUZZY_SUGGEST_THRESHOLD)

    if args.question:
        ask(chain, resolver, args.question)
        return

    print("Chatbot ontologique — posez une question (Ctrl+C pour quitter)\n")
    while True:
        try:
            question = input("Question> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAu revoir.")
            break

        if not question:
            continue

        ask(chain, resolver, question)


if __name__ == "__main__":
    main()
