default: tinman

.PHONY: default tinman test

tinman:
	docker build -t unimatrix525/tinman .

test:
	docker run unimatrix525/tinman /bin/sh -c "cd /tinman/test && python -m unittest *_test.py"
