"""Interface en ligne de commande du chatbot ontologique.

Usage :
    # Question unique, réponse puis sortie (utile en script / non-interactif)
    python -m chatbot.cli "Quels médecins soignent des patients atteints de diabète ?"

    # Mode interactif : boucle de questions tant qu'aucune question n'est fournie
    python -m chatbot.cli
"""
import argparse
import logging

from .config import FUZZY_SUGGEST_THRESHOLD
from .graph_qa import build_chain
from .llm import get_llm
from .resolver import QuestionResolver, Resolution, Status


def _input(prompt: str) -> str:
    """input() qui renvoie une chaîne vide si l'entrée standard est fermée."""
    try:
        return input(prompt).strip().lower()
    except EOFError:
        print()
        return ""


def choose_entity(resolution: Resolution) -> str | None:
    """Demande à l'utilisateur quelle entité il désignait.

    Renvoie le label retenu, ou None pour garder sa formulation.
    """
    text = resolution.mention.text
    candidates = resolution.candidates

    if resolution.status is Status.SUGGESTION:
        label = candidates[0].label
        answer = _input(f'Vouliez-vous dire "{label}" au lieu de "{text}" ? [O/n] ')
        return label if answer in ("", "o", "oui", "y", "yes") else None

    if resolution.status is Status.AMBIGUOUS:
        print(f'"{text}" peut désigner plusieurs entités :')
    else:
        print(f'Aucune entité ne correspond à "{text}". Entités proches du même type :')
    for i, match in enumerate(candidates, start=1):
        print(f"  {i}. {match.label}")
    print(f'  0. Garder "{text}"')

    while True:
        answer = _input("Votre choix [0] : ")
        if answer in ("", "0"):
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1].label
        print(f"Choix invalide : entrez un nombre entre 0 et {len(candidates)}.")


def ask(chain, resolver: QuestionResolver, question: str) -> None:
    reformulated = resolver.reformulate(question, choose_entity)
    if reformulated != question:
        print(f"\nQuestion reformulée : {reformulated}")
    result = chain.invoke({"query": reformulated})
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
        "-q", "--quiet",
        action="store_true",
        help="Masque les logs verbeux de la chaîne LangChain.",
    )
    args = parser.parse_args()

    if not args.quiet:
        # Trace les corrections d'entités appliquées d'office.
        resolver_logger = logging.getLogger("chatbot.resolver")
        resolver_logger.setLevel(logging.INFO)
        resolver_logger.addHandler(logging.StreamHandler())

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
