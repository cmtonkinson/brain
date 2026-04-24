"""Demo echo op that returns a static string."""

# Note: The signature for this function will be defined by the Execution's
# execution environment for Logic Skills. For now, we assume a simple no-argument
# function that returns a JSON-serializable value.


def execute():
    """Execute the op."""
    return "Hello, World!"
