# 1 - Create a Modal account

Sign up at <https://modal.com/>.

We'll be running our application on Modal, which provides serverless
infrastructure for data science and ML projects with a best-in-class
developer experience. The free tier easily covers hundreds of requests
per day for this app.

Once you've created the account, generate a token:

```bash
make modal-token
```

This opens a browser window, authenticates you, and prints a token ID and
secret. Copy them into your `.env.dev` (or `.env` for prod):

```
MODAL_TOKEN_ID=...
MODAL_TOKEN_SECRET=...
```

Then confirm the token is registered with Modal:

```bash
make modal-auth
```

# 2 - Create a Gemini API key

We use language models and embeddings from Google's Gemini API.

Get a key at <https://aistudio.google.com/api-keys>.

Add it to `.env.dev` as:

```
GEMINI_API_KEY=AIza...
```

# 3 - Configure a MongoDB document store

We store our source corpus in MongoDB, a document database. Documents are
JSON-like objects, which makes them easy to work with from Python.

The easiest way to run MongoDB is with
[MongoDB Atlas](https://www.mongodb.com/cloud/atlas/), the managed
service from the creators of MongoDB. The free tier comfortably covers
this project.

Alternatively, you can run MongoDB locally or on a server you control,
but we don't include instructions for that path. Once your database is
up, jump to step f.

## a - Create a MongoDB Atlas account

Follow the instructions at <https://www.mongodb.com/cloud/atlas/lp/try4>.

## b - Create a cluster

![create-cluster](./mongodb/create-cluster.png)

## c - Create a database and collection

A document collection is like a table in a relational database.

Name them `fsdl-dev` and `ask-fsdl`, respectively.

For production you'd use `fsdl-prod`; the environment is selected by the
`ENV` variable (`ENV=dev` by default, `ENV=prod` for production).

![create-database-1](./mongodb/create-database-1.png)
![create-database-2](./mongodb/create-database-2.png)

## d - Create a user and password

See instructions [here](https://www.youtube.com/watch?v=5-hybmPlZ_U&t=11s).

Save the password somewhere safe, like a password manager.

Add the username and password to `.env.dev`:

```
MONGODB_USER=...
MONGODB_PASSWORD=...
```

**Tip:** if your password contains special characters, paste it raw.
The code URL-encodes it automatically.

## e - Enable network access

Add `0.0.0.0/0` (allow from anywhere) to your IP Access List. Modal
containers have dynamic outbound IPs, so restricting by IP would break
the connection from the deployed backend.

![network-access-1](./mongodb/network-access-1.png)
![network-access-2](./mongodb/network-access-2.png)

## f - Get the connection information

To connect, we need three pieces of information from the
"Connect" tab of the Atlas dashboard:

1. The hostname of the cluster
2. A database user with read/write access
3. That user's password

If you already entered the username and password in step d, you only
need the hostname now.

From the **Connect → Drivers** screen, your connection string will look
like:

```
mongodb+srv://<username>:<password>@cluster0.abc12.mongodb.net/?retryWrites=true&w=majority
```

Extract the hostname (`cluster0.abc12.mongodb.net`) and add it to
`.env.dev`:

```
MONGODB_HOST=cluster0.abc12.mongodb.net
MONGODB_DATABASE=fsdl-dev
MONGODB_COLLECTION=ask-fsdl
```

**Do not** paste the full connection string into `.env` — `docstore.py`
constructs it from `MONGODB_HOST`, `MONGODB_USER`, and `MONGODB_PASSWORD`.

![connect-1](./mongodb/connect-1.png)
![connect-2](./mongodb/connect-2.png)
![connect-3](./mongodb/connect-3.png)

# Recap: your `.env.dev` should now contain

```
# Modal
MODAL_TOKEN_ID=...
MODAL_TOKEN_SECRET=...

# Gemini
GEMINI_API_KEY=...

# MongoDB
MONGODB_USER=...
MONGODB_PASSWORD=...
MONGODB_HOST=cluster0.xxxxx.mongodb.net
MONGODB_DATABASE=fsdl-dev
MONGODB_COLLECTION=ask-fsdl
```

If any of these are missing, `make secrets` will fail with a clear error
telling you which one to add.
