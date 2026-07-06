from setuptools import setup, find_packages

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name="SharesightAPI",
    version="1.3.0",
    author="Joshua Leaper",
    author_email="poshernater163@gmail.com",
    description="A Python library to access your sharesight portfolio information",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Poshy163/Sharesight-API",
    packages=find_packages(),
    # Ship the inline type hints (PEP 561).
    package_data={"SharesightAPI": ["py.typed"]},
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ]
)
