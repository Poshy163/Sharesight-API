from setuptools import setup, find_packages

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name="SharesightAPI",
    version="1.0.5",
    author="Joshua Leaper",
    author_email="poshernater163@gmail.com",
    description="A Python library to access your sharesight portfolio information",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Poshy163/Sharesight-API",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ]
)
