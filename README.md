# FLAT-PY: Formal Languages as Types, for Python

[![Build][build-badge]][build-link]

[build-badge]: https://github.com/paulzfm/flat-py/actions/workflows/build.yml/badge.svg?branch=main
[build-link]: https://github.com/paulzfm/flat-py/actions/workflows/build.yml

String is a universal representation of many types of data,
e.g., email addresses, URLs, Unix file paths, HTML, and JSON.
These types of data are **conceptually different**, but all have a unified string type,
e.g., `str` in Python, `java.lang.String` in Java.
This can bring problems like "you promise me JSON and then sent XML"[^1] as shown in the following Python snippet:

```python
def send(json: str) -> None:
    ...


send('<error>404</error>')
```

FLAT-PY is a **Python testing framework** that aims to detect such **format/syntax incompatibility** issues and
avoid unexceptional failures and the severe vulnerabilities they cause.
We apply a syntax-aware, type-directed approach, treating **Formal Languages as Types** (FLAT).

Read our paper *FLAT: Formal Languages as Types* for more technical details.

## Features

+ Convenient annotations for users to define formal language types and to attach them directly to Python code.
+ Built-in types for email addresses, URLs, and JSON (and more in future).
+ Arbitrary Python expressions/functions as expressive semantic constraints.
+ Pre-/post-conditions as test oracles and contracts.
+ Language-based fuzzing for free.

FLAT-PY is an *all-in-one* framework that reduces user efforts in
+ API documentation (formal language specifications),
+ input validations (automated runtime type checking),
+ malicious input detection (language types define the secured input space),
+ language-based fuzzing (the `fuzz` annotation),
+ test oracles (via pre-/post-conditions).

## Build

### Option 1: Via Docker

In the project root directory, build the image first:

```shell
docker build -t flat-py .
```

This can take a while. Once the image is successfully built, you can enter its bash shell:

```shell
docker run -it flat-py:latest
```

### Option 2: From Source (in Unix)

As ISLa is still using the deprecated `pkg_resources`, it is recommended to use Python `3.11`.

Setting up a virtual environment is recommended. In the project root directory:

```shell
python3.11 -m venv .venv
source .venv/bin/activate
```

In the virtual environment, install dependencies and test the CLI:

```shell
pip install --upgrade pip
pip install -e .
python -m flat.py --help
```

Setting up the development environment with `mypy`:

```shell
pip install -e ".[dev]"
```

Generating distribution packages with `build`:

```shell
pip install --upgrade build
python -m build
```

## Usage

The basic usage is:

```shell
python -m flat.py [-o OUTPUT_DIR] INPUT_FILE
```

FLAT-PY processes the user's Python file `INPUT_FILE` attached with FLAT annotations,
and generates an **instrumented** version in `OUTPUT_DIR` (default: `examples/out/`).
Run this instrumented version to check for any type errors.

For example, to check the `hostname.py` example:

```shell
python -m flat.py examples/demo/hostname.py
python examples/out/hostname.py
```

To check all the examples in the directory `examples/demos`, run:

```shell
python run_demos.py
```

## Quick Tour by Example

Consider an ad hoc parser that aims to extract the hostname part from the input `url`:

```python
def get_hostname(url: str) -> str:
    """Extract the hostname part."""
    start = url.find('://') + 3
    end = url.find('/', start)
    host = url[start:end]
    return host
```

We wish to save the extracted hostname in a database table named `hosts`:

```python
def save_hostname(url: str, db_cursor: MysqlCursor):
    sql_temp = "INSERT INTO hosts VALUES ('{host}')"
    hostname = get_hostname(url)
    sql_query = sql_temp.format(host=hostname)
    db_cursor.execute(sql_query)
```

### Issue: SQL Injection

The above code is **unsafe**: it suffers from SQL injection if we feed the malicious input below to `get_hostname`:

```python
malicious_url = "https://localhost'); DROP TABLE users --/"
```

The output `localhost'); DROP TABLE users --` is indeed not a legal hostname.
Using it to instantiate `sql_temp`, we obtain a SQL query that contains a dangerous `DROP TABLE` command:

```sql
INSERT INTO hosts
VALUES ('localhost');
DROP TABLE users --')
```

### Solution: Language Types

Such an issue can be avoided if we force the `url` input to be a valid URL but not any string.
In FLAT-PY, we achieve this by **refining** the type signature of the `get_hostname` function:

```python
from flat.types import URL, Host


def get_hostname(url: URL) -> Host:
    ...
```

The language types `URL`[^2] and `Host` restrict the set of valid strings for the input and the output, respectively.
Feeding `malicious_url` to `get_hostname` now causes a type error:

```text
Type mismatch for argument 0 of method get_hostname
  expected type: URL
  actual value:  "https://localhost'); DROP TABLE users --/"
```

### Fuzz Testing

To better know if the code is functionally correct, meaning it behaves normally on valid URL inputs,
here we apply **language-based fuzzing**.
The idea is to rely on a backend language-based fuzzer to produce random input strings that match the syntax,
and test our functions against them.
FLAT-PY offers a `fuzz` function to enable such a feature:

```python
from flat.py import fuzz

report = fuzz(get_hostname, 50)
```

FLAT-PY now produces 50 random URLs (with the help of a language-based fuzzer),
tests the target function `get_hostname`, and finally generates a test `report`.
One can print the report via a utility function:

```python
from flat.py.utils import print_fuzz_report

print_fuzz_report(report)
```

Note that the implementation of `get_hostname` is buggy:
it cannot correctly handle URLs with empty paths, e.g., `http://W`.

### Oracles

Apart from format validation/checking, functional correctness is also of great importance.
The contract that describes the required behaviors can serve as a **test oracle**.
FLAT-PY offers `requires` and `ensures` decorators to specify pre-/post-conditions,
and a `select` function to extract a particular substring via an XPath:

```python
from flat.py import ensures
from flat.lib import select, xpath


@ensures(lambda url, ret: ret == select(xpath(URL, "..host"), url))
def get_hostname(url: URL) -> Host:
    ...
```

This post-condition states that the output value (bound to the last lambda parameter `ret`) equals the hostname extracted by `..host`:
it refers to the (unique) node labeled with nonterminal symbol `host`,
which refers to the hostname part, in the derivation tree of `url`.

For the full example, see `examples/demo/hostname.py`.

## Case Studies

The case studies mentioned in Section 7 of the paper are included in `examples/paper`.
The subdirectory `logs` includes the output logs that match the paper results.
To check these files yourself, run:

```shell
python run_cases.py
```

This will take a couple of minutes.

[^1]: Lyrics from the song "You Give REST a Bad Name" (https://dylanbeattie.net/songs/bad_name.html).
[^2]: Here, we only consider a simplified version of URLs without IP addresses, queries, or fragments.