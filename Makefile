PYTHON ?= python3
IMAGE ?= unimatrix525/tinman
HIVE_RPC ?= https://api.hive.blog
FASTGEN_RPC ?= http://127.0.0.1:9990
HIVE_IMAGE ?= registry.gitlab.syncad.com/hive/hive/testnet:1.28.7@sha256:4b5720852668ab9cbdd41e2f16543c3ccd30fb3fc217174d312f38ff86867c79
DOCKER_CONTEXT ?= calculon
MATRIX_TINMAN_IMAGE ?= tinman:modernization
GET_DEV_KEY ?= get_dev_key
SIGN_TRANSACTION ?= sign_transaction

.PHONY: default tinman test tox artifacts docker-test compat-read-only compat-fastgen compat-matrix

default: tinman

tinman:
	docker build -t $(IMAGE) .

test:
	$(PYTHON) -W error::DeprecationWarning -m unittest discover -s test -p '*_test.py'
	$(PYTHON) -m tinman --help

tox:
	$(PYTHON) -m tox

artifacts:
	$(PYTHON) scripts/check_artifacts.py

docker-test: tinman
	docker run --rm --entrypoint python $(IMAGE) -W error::DeprecationWarning -m unittest discover -s test -p '*_test.py'
	docker run --rm $(IMAGE) --help

compat-read-only:
	$(PYTHON) scripts/hive_compatibility.py read-only --endpoint $(HIVE_RPC)

compat-fastgen:
	$(PYTHON) scripts/hive_compatibility.py fastgen --endpoint $(FASTGEN_RPC) --hive-image $(HIVE_IMAGE) --get-dev-key $(GET_DEV_KEY) --signer $(SIGN_TRANSACTION)

compat-matrix:
	$(PYTHON) scripts/docker_fastgen_matrix.py --context $(DOCKER_CONTEXT) --tinman-image $(MATRIX_TINMAN_IMAGE)
