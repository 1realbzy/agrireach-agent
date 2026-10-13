# Thin wrapper; run.sh does the work (so it also works where make is not installed).
.PHONY: run test
run:
	./run.sh
test:
	./run.sh test
