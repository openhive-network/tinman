PYTHON ?= python3
IMAGE ?= unimatrix525/tinman

.PHONY: default tinman test tox docker-test

default: tinman

tinman:
	docker build -t $(IMAGE) .

test:
	$(PYTHON) -W error::DeprecationWarning -m unittest discover -s test -p '*_test.py'
	$(PYTHON) -m tinman --help

tox:
	$(PYTHON) -m tox

docker-test: tinman
	docker run --rm --entrypoint python $(IMAGE) -W error::DeprecationWarning -m unittest discover -s test -p '*_test.py'
	docker run --rm $(IMAGE) --help
