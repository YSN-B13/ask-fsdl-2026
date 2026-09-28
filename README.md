# 🥞🦜 askFSDL 🦜🥞

askFSDL is a demonstration of a retrieval-augmented question-answering application.

You can try it out via the Discord bot frontend in the
[Full Stack Discord](https://fsdl.me/join-discord-askfsdl)!

We use our educational materials as a corpus:
the [Full Stack LLM Bootcamp](https://fullstackdeeplearning.com/llm-bootcamp),
the [Full Stack Deep Learning course](https://fullstackdeeplearning.com/course), and
the [Opinionated LLM++ Lit Review](https://tfs.ai/llm-lit-review).

So the resulting application is great at answering questions like

- Which is cheaper: running experiments on cheap, slower GPUs or fast, more expensive GPUs?
- How do I build an ML team?
- What's a data flywheel?
- Should I use a dedicated vector store for my embeddings?
- What is zero-shot chain-of-thought reasoning?

## Contents

- [Stack](#stack)
- [How to run it](#experimental-how-to-run-it)
  - [I. Setup the configuration file](#i-setup-the-configuration-file)
  - [II. Prepare the Python environment](#ii-prepare-the-python-environment)
  - [III. Set up managed services](#iii-set-up-managed-services-and-configure-the-app-to-use-them)
  - [IV. Push configuration to Modal](#iv-push-all-of-the-configuration-information-to-modal)
  - [V. Extract and store data](#v-extract-and-store-data)
  - [VI. Run the backend](#vi-run-the-backend)
  - [VII. Run the Discord bot](#vii-run-the-discord-bot-optional)

## Stack

We use [`langchain`](https://github.com/hwchase17/langchain)
to organize our LLM invocations and prompt magic.

For the language model and embeddings, we use Google's
[Gemini API](https://ai.google.dev/gemini-api) via
[`langchain-google-genai`](https://python.langchain.com/docs/integrations/providers/google/).
The chat model is `gemini-3.7-flash` and embeddings use
`gemini-embedding-001`.

We stood up a MongoDB instance on
[Atlas](https://www.mongodb.com/atlas/database)
to store our cleaned and organized document corpus.
See the `Running ETL to Build the Document Corpus` notebook for details.

For fast search of relevant documents to insert into our prompt,
we use a [FAISS index](https://github.com/facebookresearch/faiss).

We host the application backend on
[Modal](https://modal.com/),
which provides serverless execution and scaling.
That's also where we execute batch jobs,
like writing to the document store and refreshing the vector index.

For creating a simple user interface in pure Python,
we use [Gradio](https://gradio.app/).
This UI is great for quick tests without deploying a full frontend
but with a better developer experience than curl-ing from the command line.

We host the Discord bot on
[Modal](https://modal.com/)
as well, relying on Discord's
[interactions endpoints](https://discord.com/developers/docs/tutorials/upgrading-to-application-commands#adding-an-interactions-endpoint-url)
to run the bot serverlessly.

## EXPERIMENTAL: How To Run It

> These instructions are a community contribution
> (thanks [@candidosales](https://github.com/candidosales)!)>
> and are provided on a best-effort basis.
>
> These instructions detail steps in the process for setting up this project from scratch.
> They cover Python environment setup up through deployment of the backend.
> They do not cover Python installation or creation of the Discord bot.
>
> If you notice and resolve an error during setup, we'd be grateful if you submitted a PR to fix it
> and these docs.

### I. Setup the configuration file

The `Makefile` gets configuration information like usernames and secrets from
[dotenv files](https://www.dotenv.org/docs/security/env.html).

We've included an empty template file, `.env.example`. Copy it to `.env` with:

```bash
cp .env.example .env
```

If you want a dev environment you can also copy it to `.env.dev`:

```bash
cp .env.example .env.dev
```

To switch between the production and development environments, set the `ENV` variable to `prod` or `dev`, respectively.

```bash
export ENV=dev  # set it as an environment variable
ENV=prod make help # or set it for each make command
```

#### Required environment variables

Your `.env.dev` (or `.env`) must define:

| Variable | Purpose |
|----------|---------|
| `MONGODB_USER` | MongoDB Atlas username |
| `MONGODB_PASSWORD` | MongoDB Atlas password |
| `MONGODB_HOST` | Atlas cluster hostname (e.g. `cluster0.abc12.mongodb.net`) |
| `MONGODB_DATABASE` | Database name (e.g. `fsdl-dev`) |
| `MONGODB_COLLECTION` | Collection name (e.g. `ask-fsdl`) |
| `GEMINI_API_KEY` | Google AI Studio key |
| `MODAL_TOKEN_ID` | Modal token (from `make modal-token`) |
| `MODAL_TOKEN_SECRET` | Modal token secret |
| `DISCORD_AUTH` | Discord bot token |
| `DISCORD_PUBLIC_KEY` | Discord app public key (for signature verification) |
| `DISCORD_CLIENT_ID` | Discord application ID |
| `DISCORD_MAINTAINER_ID` | (Optional) Discord user ID for error notifications |

### II. Prepare the Python environment

There are [many ways](https://xkcd.com/1987/)
to manage Python environments.
We use `pyenv` + `pyenv-virtualenv`,
but you're welcome to use another method.

The only restriction is that the `Makefile` presumes that `python -m pip install` works for installing into the intended environment.
If you violate this assumption, you will not be able to use any of the `make` commands.

If you're not using `pyenv` + `pyenv-virtualenv`,
skip to step 4.

#### 1 - Install `pyenv` + `pyenv-virtualenv`

Follow the installation instructions
[here for `pyenv`](https://github.com/pyenv/pyenv)
and [here for `pyenv-virtualenv`](https://github.com/pyenv/pyenv-virtualenv).
Don't forget to follow the instructions for
setting up your shell environment!

To activate `pyenv` and `pyenv-virtualenv`,
restart your shell after setting up the shell environment.

#### 2 - Install Python

`pyenv` installs Python.

We use Python 3.10 and later in our development.
You can install it with:

```bash
pyenv install 3.10.9
```

#### 3 - Create and activate the virtual environment

Environments isolate libraries used in one context from those used in another context.

For example, we can use them to isolate the libraries used in this project from those used in other projects.

Done naively, this would result in an explosion of space taken up by duplicated libraries.

Virtual environments allow the sharing of Python libraries across environments if they happen to be using the same version.

We create one for this project with:

```bash
pyenv virtualenv 3.10.9 ask-fsdl
```

To start using it, we need to "activate" it:

```bash
pyenv activate ask-fsdl
```

We've set it as the default environment for this directory with:

```bash
pyenv local ask-fsdl
```

which generates a `.python-version` file in the current directory.

#### 4 - Install the dependencies

Now that we have an environment for our project,
we can install the dependencies.

If you're interested in contributing, run

```bash
make dev-environment
```

which adds a few code quality checkers.
Otherwise, run

```bash
make environment
```

### II. Set up managed services and configure the app to use them

From here, the `Makefile` will handle a lot of the heavy lifting
for coordinating all the pieces of the project.

Run `make help` to see all of the things it can do.

```bash
make help
```

However, it needs some information from you
and some resources, like accounts on managed services,
cannot be created automatically.

Thanks to community contributions, we can share a best-effort guide to set the dotenv file[here](./setup/).

### IV - Push all of the configuration information to Modal

For the application to run, it needs the information in the dotenv file.

We push that information to Modal with

```bash
make secrets
```

As a side effect, this will confirm that all of the necessary information is provided.


Verify the secrets landed in the dev environment:

```bash
modal secret list --env dev
```

You should see both `mongodb-fsdl` and `gemini-api-key-fsdl`.

If you want every `modal` command from your machine to default to the dev environment:

```bash
modal config set-environment dev
modal config show
```

#### (Optional) Reset the document store

If you ever need to start over with an empty collection — for example, after
changing the embedding model — drop it first:

```bash
modal run --env dev app.py::drop_docs --db "fsdl-dev" --collection "ask-fsdl"
```

⚠️ This is destructive. Only run it if you intend to rebuild the corpus from scratch.

### V. Extract and store data

The sources used by the chatbot come from many places
and are stored in a variety of formats.

We bring them in and format them all as JSON documents
with a particular structure.

We also make them searchable with a
[vector index](https://www.pinecone.io/learn/wild/).

#### 1 - Extract data, transform it, and load it into the document store

```bash
make document-store
```

Optionally, to learn more about the process,
check out the [included Jupyter notebook](./Running%20ETL%20to%20Build%20the%20Document%20Corpus.ipynb).

Run all steps to create the full document store.

After the ETL completes, add a unique index on `metadata.sha256` so
re-running the ETL doesn't create duplicates:

```bash
python - <<'PY'
import docstore
col = docstore.get_database("fsdl-dev")["ask-fsdl"]
col.create_index("metadata.sha256", unique=True)
print(f"index created. documents: {col.count_documents({})}")
PY
```

#### 2 - Create a vector index for embedding-based search

We use a vector index to find the most similar documents to a given query.

You can create it with

```bash
make vector-index
```

At time of writing, the vector index is a
[FAISS index](https://github.com/facebookresearch/faiss)
that is read from disk at query time.

### VII. Run the backend

You're now ready to ask the chatbot a question!

Use this command, and feel free to substitute your own query.

```bash
make cli-query QUERY="What is zero-shot chain-of-thought?"
```

You can turn this into a web service with

```bash
make backend
```

### VIII. Next steps

### VII. Run the Discord bot (optional)

The Discord bot runs on Modal as a serverless webhook.

1. Create a Discord application at https://discord.com/developers/applications
2. Under "Bot", enable **Message Content Intent**
3. Copy the bot token, public key, and application ID into `.env.dev`
4. Register the slash command with Discord:

   ```bash
   make slash-command
   ```

5. Deploy the bot:

   ```bash
   make frontend
   ```

6. Copy the deployed URL from the Modal output, then paste it into
   Discord Developer Portal → "Interactions Endpoint URL".

Discord will PING the endpoint immediately to verify. If the bot is
running correctly, it will respond with a PONG.

## Known issues

- **`modal secret list` shows an empty table** — you're probably in the wrong
  Modal environment. Run `modal environment list`, then
  `modal secret list --env dev`.
- **`Function has not been hydrated` during ETL** — the `etl-shared` app
  needs its own run context. The CLI path (`modal run etl/pdfs.py ...`)
  handles this automatically; the notebook needs `async with shared.app.run():`.
- **PDF URLs 404 or timeout** — the `data/llm-papers.json` list ages as
  papers move. Failures are logged and skipped; a ~30% failure rate is normal.
- **`smart_open` raises `ImportError: http functionality`** — install the
  extra: `"smart-open[http]>=7.0"` in the ETL image spec.
