### Version 1.9.0

#### New features

* [feat(misc)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/910a1f1d201c262e218da27865b7e9487271e4d2): Add verbose option to set_dir (#258). Committed by wpbonelli on 2025-11-06.
* [feat(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/c8a136872198e1d9f36be74e958d003cdc75f6eb): Improve models API (#268). Committed by wpbonelli on 2026-01-15.
* [feat(programs)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/5e85417270cea1b4e5081d531c8c98b072acc371): Add programs API (#270). Committed by wpbonelli on 2026-01-16.
* [feat(version)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/f9e26de1efdda95d509c0cc0cb1cf886a3f6c278): Add project version management tool (#284). Committed by wpbonelli on 2026-02-13.
* [feat(dfns)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/aa99c56f5bc5fc2e846262d5bb5c6d80dc9d69b9): Improve DFNs API (#271). Committed by wpbonelli on 2026-02-23.

#### Bug fixes

* [fix(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/d736dfd881cbc39d2fe82180d98d1d2a0130f146): Backwards-compatibility adjustments (#272). Committed by wpbonelli on 2026-01-20.
* [fix(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/a1497797fc9b1a7cf4ed7cd72e43f0b290fd49d4): Miscellaneous fixes (#273). Committed by wpbonelli on 2026-01-21.
* [fix(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/5dce2af85369063d037c58a3bfc12a2e32c74770): Check env var before auto-sync, fix tests (#275). Committed by wpbonelli on 2026-01-23.
* [fix(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/f6cc9bbbcc8577a4384e18159597c128181e3ecf): Exclude output files from registries (#274). Committed by wpbonelli on 2026-01-23.
* [fix(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/5aa924836fe700bb7ccf4c56faeea52b72368bb5): Auto-sync only on api commands (#277). Committed by wpbonelli on 2026-02-10.
* [fix(programs)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/2674176f6151814fa158269478015b1b175ba884): Exe path at program or dist level, add tests, update docs (#281). Committed by wpbonelli on 2026-02-11.
* [fix(programs)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/a9584012258e5ca52be86a7d631da2f0bf10b75c): Multiple fixes/improvements (#282). Committed by wpbonelli on 2026-02-12.
* [fix](https://github.com/MODFLOW-ORG/modflow-devtools/commit/18af51ae53bf1c8fb877620b0fa26e7be28ea210): More fixes/improvements (#283). Committed by wpbonelli on 2026-02-12.
* [fix](https://github.com/MODFLOW-ORG/modflow-devtools/commit/448993522772773ea650206e94185ad8ec72bb83): Multiple fixes (#285). Committed by wpbonelli on 2026-02-20.
* [fix(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/02ab50dac6540191914506329dcc9ef52820f7ff): Fix model registry generation from release assets (#290). Committed by wpbonelli on 2026-02-23.
* [fix(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/ebaffb9e2d364210789cd003a5654f4d6741436d): Restore dfn module and tests (#291). Committed by wpbonelli on 2026-02-23.
* [fix(tests)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/d83dfa9470c619693c36da2aacd526916141aec1): Fix test branch (#292). Committed by wpbonelli on 2026-02-24.
* [fix(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/9dfa972efffe310f5de79fa31cdc0235716edc2c): Don't exclude .obs files when copying input files (#293). Committed by wpbonelli on 2026-02-25.

#### Refactoring

* [refactor(programs)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/bb76dc1c36f235b3e8bd5b10231661081dda7fe9): Multiple programs api improvements (#276). Committed by wpbonelli on 2026-02-09.
* [refactor(registries)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/75c6909a6202da02b30a1b7b5743e75498aa26a7): Leaner model/program registry file contents (#279). Committed by wpbonelli on 2026-02-10.
* [refactor(dependencies)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/fa8c8d9753da38a9a400c0f7d736944d08a3a059): Introduce ecosystem group (#289). Committed by wpbonelli on 2026-02-22.

### Version 1.8.0

#### New features

* [feat(programs)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/7424efa236c67365889081f857127cb2ccfa19c3): Add programs module and database (#243). Committed by wpbonelli on 2025-10-15.

#### Refactoring

* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/98215fd29a46cd63c964613dba14fbacfed26721): Move drop_none_or_empty to misc module. Committed by w-bonelli on 2025-10-29.
* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/e1264de9eef2f63b030cb75584e91d9cb1422d2f): Update programs database (#254). Committed by wpbonelli on 2025-10-29.

### Version 1.7.0

#### New features

* [feat(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/910ab4f252a56718302e41a450b377351a30a387): Add dfn container, parser, toml conversion script (#167). Committed by wpbonelli on 2024-12-11.
* [feat(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/01b95b0745a4fc4767cf8074738e2968f1e206b1): Toml load support, switch to tomli, add tests (#173). Committed by wpbonelli on 2025-01-14.
* [feat](https://github.com/MODFLOW-ORG/modflow-devtools/commit/1d787a42174a4d44e2ab908f84b6339286b8e47c): Models api (#191). Committed by wpbonelli on 2025-03-06.
* [feat](https://github.com/MODFLOW-ORG/modflow-devtools/commit/e142df74c8a037f9c921e8a85a21ae28009f55c0): Model mapping (#192). Committed by wpbonelli on 2025-03-07.
* [feat(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/aa45c48d3a4c3ea3e376c5c84ab0693732979316): Support example models (#197). Committed by wpbonelli on 2025-03-11.
* [feat(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/0ea364bfea83b3351afef10190f01203daddb5c4): Add example scenario mapping (#198). Committed by wpbonelli on 2025-03-11.
* [feat(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/910672795a5a87ad3ea78902626f04dd3d9c036c): Add mf2005 models from modflow6-testmodels repo (#206). Committed by wpbonelli on 2025-04-08.
* [feat(misc)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/366df8a35e5ead88713312ca5ea18a3b5a504b4b): Add try_get_enum_value function (#208). Committed by wpbonelli on 2025-04-22.
* [feat(misc)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/134fb4c91cfa2382c014114ff292a05fa0305a2b): Add cd alias for set_dir (#221). Committed by wpbonelli on 2025-05-20.

#### Bug fixes

* [fix(fixtures)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/90316a1cca281ac36062da946374145bda421d52): Don't use square brackets in tempdir paths (#160). Committed by wpbonelli on 2024-06-10.
* [fix(download.py)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/6f84edb6c58d22531b538fa9e8044f3aff9e6173): Accommodate missing gh api response item (#162). Committed by wpbonelli on 2024-10-02.
* [fix(test_meson_build)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/acec996c1993840aa38abe8df83b03d31279e4f1): Use requires_exe instead of requires_pkg (#164). Committed by Mike Taves on 2024-12-09.
* [fix(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/d9a4212229c84c788ec791ee6dac704ef290e5d8): Include missing attributes (#176). Committed by wpbonelli on 2025-01-25.
* [fix(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/50cba8b0fd8426dd04e7c59df88ac24b70853a64): Mark transient blocks (#178). Committed by wpbonelli on 2025-01-26.
* [fix(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/e80929551dac3675d7bb288084347e9cf6190c09): Rename sub -> ref (#180). Committed by wpbonelli on 2025-01-31.
* [fix(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/b15a699981a74efae27250970c875326d9a3df5d): Remove some special handling for subpackages (#181). Committed by wpbonelli on 2025-01-31.
* [fix(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/c36f502f9cda15817684a11cbfa6d3cf6ded8a7c): Keep block attribute for now (#182). Committed by wpbonelli on 2025-02-03.
* [fix(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/d54312569dc6f59a6362f8a60dd2b54bed694d5a): Block attribute first (#183). Committed by wpbonelli on 2025-02-03.
* [fix(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/931c497e71b3b7a148f1655d5aff6af8fd410849): Rename transient -> transient_block (#184). Committed by wpbonelli on 2025-02-04.
* [fix](https://github.com/MODFLOW-ORG/modflow-devtools/commit/642c2d1314d1e0d547d906d139da54c7733ded62): Filelock when fetching zips (#200). Committed by wpbonelli on 2025-03-18.
* [fix(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/1ff3c0f70364f71a49738c26915f933b694df09d): Include files in nested folders (#201). Committed by wpbonelli on 2025-03-19.
* [fix(models.py)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/6534389ba2c5f8ee8d06297be28375cd28ade207): Add retries for transient network errors (#205). Committed by wpbonelli on 2025-04-07.
* [fix(LocalRegistry)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/aa62b34711e157935deb653dd2c44bad499894ee): Fix string joining in dir not found error case (#213). Committed by wpbonelli on 2025-05-02.

#### Refactoring

* [refactor](https://github.com/MODFLOW-ORG/modflow-devtools/commit/438847cbb07ad01782a50fd01a1c907323fda31b): Use pathlib and subprocess; refactor other aspects (#166). Committed by Mike Taves on 2024-12-09.
* [refactor(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/52e846b6f4099e6c80b1f6323670b237cbfc0fd6): Move to file (#170). Committed by wpbonelli on 2025-01-03.
* [refactor(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/5074b21cff9ccdf56e0783cbe5e0a7f9a42c65f5): Use explicit table names in toml format (#174). Committed by wpbonelli on 2025-01-17.
* [refactor(download)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/6957554ebec45e89cda5188358aa448586d71105): Remove asset/artifact utilities (#175). Committed by wpbonelli on 2025-01-17.
* [refactor(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/ba6fe08ea2da3ffe3c7164d52d8440229b822cd2): Minor toml format fixes/improvements. Committed by wpbonelli on 2025-01-26.
* [refactor(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/362ecd560944725e0ca39749ea249e3f664ec9c3): Use boltons remap, better comments/naming (#179). Committed by wpbonelli on 2025-01-26.
* [refactor(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/af441d1bcd0d940ef81944b0a2b7d445c33c9d98): Respect model names/relpaths (#199). Committed by wpbonelli on 2025-03-12.
* [refactor(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/8887835c694d5f8c1042a0fed9ae781d2495c69f): Distinguish source repo via prefix (#202). Committed by wpbonelli on 2025-04-01.
* [refactor(registry)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/016190defa046c00182421965fe8ea56b1cfd95e): Add mf6 prefix to mf6 model names (#207). Committed by wpbonelli on 2025-04-18.
* [refactor(models)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/2370d59bf6ee5a1abef3e7b0249c220461d3a898): Introduce model registry classes (#210). Committed by wpbonelli on 2025-05-01.
* [refactor(LocalRegistry)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/457ace256fa2a355bc9f81cb6ba706ffb167a06f): Support multiple model directory paths (#212). Committed by wpbonelli on 2025-05-02.
* [refactor(LocalRegistry)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/087b063cb9b0c468412d9b4a70ce891155472d63): Back to the old indexing pattern (#214). Committed by wpbonelli on 2025-05-02.
* [refactor(LocalRegistry)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/48cbf16236c71ff9ca1bab667d92e40ebf06442d): Rework index method prefix parameters (#215). Committed by wpbonelli on 2025-05-03.
* [refactor(make_registry.py)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/04ac4fa14099bcaaaf52079a8d368ca8f3b90f19): Shortcut to create default registry (#222). Committed by wpbonelli on 2025-05-20.
* [refactor(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/d169e61db1b039e56d6755993500e2d6567f723e): Rename var -> field, misc cleanup (#223). Committed by wpbonelli on 2025-05-29.
* [refactor(dfn)](https://github.com/MODFLOW-ORG/modflow-devtools/commit/9704d96d3377ed4947e536a8834909f20f0b010f): Add reader attribute to Field (#224). Committed by wpbonelli on 2025-06-03.

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

