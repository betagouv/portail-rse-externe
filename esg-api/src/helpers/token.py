import click
from flask_app.app import app
from flask_jwt_extended import create_access_token


def generate_token(email):
    with app.app_context():
        # token eternel
        return create_access_token(email,expires_delta=False)


@click.command()
@click.option(
    "--email", prompt="Entrez un e-mail", help="Identité / e-mail pour le token JWT"
)
def main(email):
    print(f"Nouveau token *permanent* pour '{email}' :")
    print(generate_token(email))


if __name__ == "__main__":
    main()
