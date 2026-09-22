"""Interface en ligne de commande du chatbot ontologique.

Usage :
    # Question unique, réponse puis sortie (utile en script / non-interactif)
    python -m chatbot.cli "Quels médecins soignent des patients atteints de diabète ?"

    # Mode interactif : boucle de questions tant qu'aucune question n'est fournie
    python -m chatbot.cli
"""
import argparse

from .graph_qa import build_chain


def ask(chain, question: str) -> None:
    result = chain.invoke({"query": question})
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
    
    chain = build_chain(verbose=not args.quiet)

    if args.question:
        ask(chain, args.question)
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

        ask(chain, question)


if __name__ == "__main__":
    main()
