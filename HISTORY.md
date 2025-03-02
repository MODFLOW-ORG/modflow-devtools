### Version 1.6.0

#### New features

* [feat(snapshots)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/4e289ee4a13d13724c5cbcb7a1ee5328fc588c13): Add --snapshot-disable cli option (#157). Committed by wpbonelli on 2024-05-21.

#### Bug fixes

* [fix(get_model_paths)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/0e3120a9d1cf53ecc98b861aeb05e3a8fa7afb71): Fix model order within scenario (#156). Committed by wpbonelli on 2024-05-21.

### Version 1.5.0

#### New features

* [feat(markers)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/1f358de2bc721c1000c3d0823b9440776432e3b0): Add no_parallel marker, support differing pkg/module names (#148). Committed by wpbonelli on 2024-04-12.
* [feat(snapshots)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/c9e445dd1544413f3729c7a78c2a77038db80050): Add snapshot fixtures, remove pandas fixture (#151). Committed by wpbonelli on 2024-05-13.

#### Refactoring

* [refactor(latex)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/827b5ec63ebe0b9ea833957637d6b60fdc2f3198): Support path-like, add docstrings (#142). Committed by wpbonelli on 2024-02-25.
* [refactor(snapshots)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/d96089e512fbb79408e4fb58c89ee63da60dc727): Move to separate module (#152). Committed by wpbonelli on 2024-05-13.

### Version 1.4.0

#### New features

* [feat(latex)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/6728859a984a3080f8fd4f1135de36bc17454098): Add latex utilities (#132). Committed by wpbonelli on 2024-01-09.
* [feat(misc)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/a9b801932866a26a996ed3a45f16048b15246472): Parse literals from environment variables (#135). Committed by wpbonelli on 2024-01-21.
* [feat(ostags)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/0ad10751ea6ce752e59d83e8cd6275906d73fa70): add OS tags for Apple silicon (#139). Committed by wpbonelli on 2024-02-18.

#### Refactoring

* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/9356e067ea813aeeeda2582cf7ec174c11d80159): Remove executables module/class (#136). Committed by wpbonelli on 2024-01-25. Should be in a major release per semver, but nothing is using it, so this should be safe.
* [refactor(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/613ad010ff6fc782f231b7fa21d1cc660732e7be): Support pytest>=8, drop pytest-cases dependency (#137). Committed by wpbonelli on 2024-01-31.

### Version 1.3.1

#### Refactoring

* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/ec3859af81e103f307586eec82e86cf63ee1e41c): Re-export get_suffixes from executables module (#128). Committed by wpbonelli on 2023-11-21.

### Version 1.3.0

#### New features

* [feat(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/0ce571411b6b35bc62d4f333d1a961bd2f202784): Add --tabular pytest CLI arg and corresponding fixture (#116). Committed by wpbonelli on 2023-09-12.
* [feat(timeit)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/506a238f6f31d827015a6c6f5ba1867ee55948a7): Add function timing decorator (#118). Committed by wpbonelli on 2023-09-12.
* [feat(executables)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/5b61a4b393b0bcd40aafeb87d1e80b3e557e0f05): Support .get(key, default) like dict (#125). Committed by wpbonelli on 2023-11-21.

#### Refactoring

* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/cd644fa90885cde04f36f24e44cfe922b2a38897): Support python 3.12, various updates (#124). Committed by wpbonelli on 2023-11-11.

### Version 1.2.0

#### New features

* [feat(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/a41caa75f8519780c7ee60daf61d8225b4380dd5): Add use_pandas pytest fixture and --pandas CLI arg (#112). Committed by wpbonelli on 2023-09-12.

### Version 1.1.0

#### Refactoring

* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/582d48a4d72f18a787216ada5befb7543cebdfcf): Deprecate misc functions, add ostags alternatives (#105). Committed by w-bonelli on 2023-08-08.
* [refactor(has_pkg)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/03ea04157190480b455e174de64c692ff3bb86a3): Introduce strict flag (#106). Committed by w-bonelli on 2023-08-12.

### Version 1.0.0

#### New features

* [feat(ostags)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/33ab22a5f7e1c88258038e9881f22c6cd537965c): Add OS tag conversion utilities (#99). Committed by w-bonelli on 2023-08-05.

#### Refactoring

* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/07bd60fff92a0dab08721c167293344a827d6345): Multiple (#100). Committed by w-bonelli on 2023-08-05.

### Version 0.3.0

#### Refactoring

* [refactor(dependencies)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/72e29e14e74c2b874cba89b1eb1563e1b4e6d0a0): Remove them, update readme (#95). Committed by w-bonelli on 2023-08-04.
* [refactor(download_and_unzip)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/c1bdb3cf7cdd988df9f3ae8d67de7496f1603c38): Return path to extract locn (#96). Committed by w-bonelli on 2023-08-04.

### Version 0.2.0

#### New features

* [feat(set_env)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/53b31cce34d221bade4c842efe3b5ed3034b2742): Add set_env contextmanager utility (#87). Committed by w-bonelli on 2023-07-26.

### Version 0.1.8

#### New features

* [feat(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/3bf76d587a04954cc68a07d38e48876d42f06b58): Discover external model repo dirs with .git suffix (#80). Committed by w-bonelli on 2023-04-21.

#### Bug fixes

* [fix(multiple)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/2307add30eb3134a786f7c722656b4d99a0fe91a): Fix some CI and fixture issues (#81). Committed by w-bonelli on 2023-04-21.

### Version 0.1.7

#### Refactoring

* [refactor(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/2bbe35f3a4b63d9c6d558d7669c986a6fb7056de): Add entries to default exe name/path mapping (#75). Committed by w-bonelli on 2023-03-01.
* [refactor(versioning)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/5fbc6b98e34afe9e43cc1d8c1b26f87e64f00699): Don't track version explicitly in readme (#76). Committed by w-bonelli on 2023-04-06.

### Version 0.1.6

#### Refactoring

* [refactor(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/a9570097d640a4c071dd1bee2d09ea99cac8ffa1): Overwrite keepable temp dirs by default (#67). Committed by w-bonelli on 2023-01-20.
* [refactor(download)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/1ced91dc3a0619016728358d69e7563e175e6fac): Refactor GH API utils, add tests, update docs (#68). Committed by w-bonelli on 2023-02-03.

### Version 0.1.5

#### Refactoring

* [refactor(metadata)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/2edeacfd8cb10081c22d1ab0799aba1fa7522c0d): Use pyproject.toml, retire setup.cfg (#63). Committed by w-bonelli on 2023-01-19.

### Version 0.1.4

#### Bug fixes

* [fix(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/8b9aeec73885c3aa2f8bbcfa84c99824fe703cbb): Fix package detection/selection (#60). Committed by w-bonelli on 2023-01-18.

#### Refactoring

* [refactor(has_pkg)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/861fa80f236bb9fcfcf4cfb1e9a391ad33076060): Use import.metadata instead of pkg_resources (#54). Committed by Mike Taves on 2023-01-09.

### Version 0.1.3

#### Bug fixes

* [fix(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/32e227bd2a6db39d3dada29ceb4ea6279f215f94): Fix test_model_mf6 fixture node id (#49). Committed by w-bonelli on 2023-01-07.

#### Refactoring

* [refactor(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/9987209620bf6b0422079d605c996c868116d725): Update defaults for model-finding fixtures (#48). Committed by w-bonelli on 2023-01-07.

### Version 0.1.2

#### Bug fixes

* [fix(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/aeccdb3d66f5f927ae9b7b4c66bf6d4d0610e379): Fix model filtering by package (#44). Committed by w-bonelli on 2023-01-04.

### Version 0.1.1

#### Bug fixes

* [fix(release)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/b8255caaeb3a7c7d140aecbf590237e4b0d8ec1d): Fix conf.py version fmt, fix update_version.py. Committed by w-bonelli on 2022-12-29.
* [fix(release)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/373d4f4fab212ea0a25b3b805a8fd363cbf50f7b): Fix changelog commit links (#38). Committed by w-bonelli on 2022-12-29.
* [fix(license)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/18417f0ca5daddde6379ec9cd28a52f0567b4f63): Remove extra LICENSE file, fix link in LICENSE.md (#39). Committed by w-bonelli on 2022-12-30.

#### Refactoring

* [refactor(utilities)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/5a1c49bef57eacb49114976f336823ab9fb8964b): Restore get_model_paths function name (#41). Committed by w-bonelli on 2022-12-30.

### Version 0.1.0

#### Refactoring

* [refactor(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/23593df7fb427d6de1d33f9aa408697d2536e473): Fix/refactor model-loading fixtures (#33). Committed by w-bonelli on 2022-12-29.

### Version 0.0.8

#### Bug fixes

* [fix(release)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/b62547bd607f9a0d3a78be61d16976bf406151f5): Exclude intermediate changelog (#28). Committed by w-bonelli on 2022-12-28.
* [fix(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/a2d4b9210db532f12cf87ae5d26582d1ed446463): Fix example_scenario fixture loading (#30). Committed by w-bonelli on 2022-12-29.

### Version 0.0.7

#### Refactoring

* [refactor(executables)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/58c3642d0e6d20d5e34783b5b61e8238058e102f): Simplify exes container, allow dict access (#24). Committed by w-bonelli on 2022-12-28.
* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/50c83a9eaed532722549a2d9da1eb79ed8cf01be): Drop Python 3.7, add Python 3.11 (#25). Committed by w-bonelli on 2022-12-28.

### Version 0.0.6

#### New features

* [feat(build)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/3108c380f29424bcdd1643479f66e849f7f762eb): Restore meson_build function (#15). Committed by w-bonelli on 2022-11-14.

#### Bug fixes

* [fix](https://github.com/MODFLOW-ORG/modflow-devtools/commit/933c79741b0e6a6db7c827414ebf635e62445772): Changes to support running of existing tests (#6). Committed by mjreno on 2022-07-20.
* [fix(ci)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/0bb31907200be32bf2a045d54131f0a1dbd0ae2f): Don't build/test examples on python 3.7 (xmipy requires 3.8+) (#10). Committed by w-bonelli on 2022-11-08.
* [fix(tests)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/3c63aaae581d335b1111b8dd2b929004b3281980): Mark test_download_and_unzip flaky (#11). Committed by w-bonelli on 2022-11-08.
* [fix(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/1e5fabdeb6d431f960316b049d68c4919650888c): Fix model-loading fixtures and utilities (#12). Committed by w-bonelli on 2022-11-11.
* [fix(misc)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/80b8d1e1549676debda09383f75db50f5f11417a): Fix multiple issues (#16). Committed by w-bonelli on 2022-11-19.
* [fix(auth)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/89db96ff5fb6e080c189f3a3e348ddf2ded21212): Fix GH API auth token in download_and_unzip (#17). Committed by w-bonelli on 2022-11-19.
* [fix(download)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/58dff9f6c1245b22e3dc10411862d6eacea42e94): Use 'wb' instead of 'ab' mode when writing downloaded files, add retries (#20). Committed by w-bonelli on 2022-12-01.

#### Refactoring

* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/5aff3427351a0bbe38927d81dad42dd5374b67be): Updates to support modflow6 autotest and remove data path. Committed by mjreno on 2022-08-05.
* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/e9e14f959e2a2ea016114c2dbfc35555b81459aa): Updates to support modflow6 autotest and remove data path. Committed by mjreno on 2022-08-05.
* [refactor(ci)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/eefb659bb04df6aa18432165850a512285812d15): Create release and publish to PyPI when tags pushed (#14). Committed by w-bonelli on 2022-11-14.
* [refactor(misc)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/1672733df1c17b802f1ade7d28db7bdb90496714): Refactor gh api & other http utilities (#18). Committed by w-bonelli on 2022-11-26.
* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/bb8fa593cd21f2c0e8e9f3a6c2125fc22d5d9858): Remove mf6 file parsing fns (moved to modflow-devtools) (#19). Committed by w-bonelli on 2022-11-28.

