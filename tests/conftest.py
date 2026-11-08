# smoke_test.py starts the whole app and is run on its own (python tests/smoke_test.py),
# so pytest must not import it while collecting the other tests.
collect_ignore = ["smoke_test.py"]
