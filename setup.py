from setuptools import find_packages, setup

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

with open("requirements.txt", encoding="utf-8") as f:
    runtime_requirements = [
        line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")
    ]

setup(
    name="SharesightAPI",
    version="1.4.0",
    author="Joshua Leaper",
    author_email="poshernater163@gmail.com",
    description="A Python library to access your sharesight portfolio information",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Poshy163/Sharesight-API",
    project_urls={
        "Changelog": "https://github.com/Poshy163/Sharesight-API/blob/main/CHANGELOG.md",
        "Documentation": "https://github.com/Poshy163/Sharesight-API#readme",
        "Issues": "https://github.com/Poshy163/Sharesight-API/issues",
        "Source": "https://github.com/Poshy163/Sharesight-API",
    },
    license="MIT",
    license_files=["LICENSE"],
    keywords=["sharesight", "portfolio", "investing", "asyncio", "aiohttp"],
    packages=find_packages(),
    # Ship the inline type hints (PEP 561).
    package_data={"SharesightAPI": ["py.typed"]},
    install_requires=runtime_requirements,
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Framework :: AsyncIO",
        "Operating System :: OS Independent",
    ],
)
