"""A fixed bridge key for tests that send frames to the Remote Script."""

TEST_KEY = "0" * 64


class StaticKey:
    def matches(self, presented):
        return presented == TEST_KEY
