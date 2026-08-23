# Changelog

## [0.9.2](https://github.com/EmaSleal/call-copilot/compare/v0.9.1...v0.9.2) (2026-08-23)


### Bug Fixes

* **mcp:** load_dotenv() with the explicit env_store path, not default search ([b3d15df](https://github.com/EmaSleal/call-copilot/commit/b3d15df7124a44ce0aeb96f05fcc45f095942f74))
* **mcp:** load_dotenv() with the explicit env_store path, not default search ([3a6d832](https://github.com/EmaSleal/call-copilot/commit/3a6d832de58b78e3aed380d1fbe535e8878d76df))

## [0.9.1](https://github.com/EmaSleal/call-copilot/compare/v0.9.0...v0.9.1) (2026-08-23)


### Bug Fixes

* **paths:** resolve app_home() to the absolute repo root, not cwd-relative ([1a5d9b4](https://github.com/EmaSleal/call-copilot/commit/1a5d9b4483426fc1bc87e6a845ac8696921661fd))
* **paths:** resolve app_home() to the absolute repo root, not cwd-relative ([de8b6ec](https://github.com/EmaSleal/call-copilot/commit/de8b6ecb7d73155a7f982c64578df93a33091f4e))

## [0.9.0](https://github.com/EmaSleal/call-copilot/compare/v0.8.0...v0.9.0) (2026-08-22)


### Features

* **cli:** add call-copilot install-mcp command ([943734e](https://github.com/EmaSleal/call-copilot/commit/943734eedb04b579770e893e4f0c53d077e60e35))


### Bug Fixes

* **ci:** install mcp for the MCP server integration test ([fbc6ab2](https://github.com/EmaSleal/call-copilot/commit/fbc6ab271c9de8da88c27f5f4f8912e131f9167b))


### Documentation

* add CI/release badges and document the catalog maintenance agent ([ab130eb](https://github.com/EmaSleal/call-copilot/commit/ab130ebf2ee8847df69bb55324192dbf2dc1ee9f))

## [0.8.0](https://github.com/EmaSleal/call-copilot/compare/v0.7.0...v0.8.0) (2026-08-19)


### Features

* **mcp:** land the read-only MCP server stack on main ([c6dddb7](https://github.com/EmaSleal/call-copilot/commit/c6dddb7c358742eee18db2af6b89dda9de549602))

## [0.7.0](https://github.com/EmaSleal/call-copilot/compare/v0.6.2...v0.7.0) (2026-08-19)


### Features

* **mcp:** add read-only content search queries for the MCP server ([c27a7ad](https://github.com/EmaSleal/call-copilot/commit/c27a7ad3accc4457ed6061f0cdbfc1c7aa45c9c7))
* **mcp:** add read-only content search queries for the MCP server ([64d9f01](https://github.com/EmaSleal/call-copilot/commit/64d9f0155ac6a6b44515d5656e64a7aeed24fc1d))

## [0.6.2](https://github.com/EmaSleal/call-copilot/compare/v0.6.1...v0.6.2) (2026-08-18)


### Documentation

* refresh promo banner with newer TUI features ([4d92af9](https://github.com/EmaSleal/call-copilot/commit/4d92af91284f9920ecb079b9770de773e0113bc6))

## [0.6.1](https://github.com/EmaSleal/call-copilot/compare/v0.6.0...v0.6.1) (2026-08-17)


### Bug Fixes

* **ci:** install rich for the categories color-swatch tests ([9b80ca6](https://github.com/EmaSleal/call-copilot/commit/9b80ca6084e69f8be7c49569423e6f137ecc6509))

## [0.6.0](https://github.com/EmaSleal/call-copilot/compare/v0.5.0...v0.6.0) (2026-08-17)


### Features

* **i18n:** add runtime ES/EN language switching to the TUI ([3ed4c5d](https://github.com/EmaSleal/call-copilot/commit/3ed4c5dce684268f6658659eddecc68e09298a8f))
* **tui:** categories color swatch, dimmed subcategories, i18n, and a Select crash fix ([e867636](https://github.com/EmaSleal/call-copilot/commit/e8676361999f8cad402ae25b7df61f738cf771a2))


### Bug Fixes

* **processing:** let tech-scout sync run inside a running event loop ([5c6d56a](https://github.com/EmaSleal/call-copilot/commit/5c6d56aafc0924a0ffab372d7fa0e4c9ee97f4fa))
* **video:** work around YouTube blocking yt-dlp's default player client ([15beaa1](https://github.com/EmaSleal/call-copilot/commit/15beaa17a960c9dde76c457bf08203e7913f4d2a))


### Documentation

* document i18n language switch, Pendientes tab, and full DB schema ([427eca5](https://github.com/EmaSleal/call-copilot/commit/427eca50376267e8ae9290276ddf879a529cf2c9))

## [0.5.0](https://github.com/EmaSleal/call-copilot/compare/v0.4.0...v0.5.0) (2026-08-17)


### Features

* **agent:** land the AI-agent CRUD foundation stack on main ([2c17c25](https://github.com/EmaSleal/call-copilot/commit/2c17c2585e1df4cd2dd24e1fb49cdc8bc85c4933))
* **agent:** wire OpenAI tool-calling catalog-maintenance agent into post-call flow ([d98e0d0](https://github.com/EmaSleal/call-copilot/commit/d98e0d08867747041a6b9a22cf6d491c0c7ef033))
* **tui:** add Pendientes tab to approve/reject agent-proposed deletes ([54c0a6a](https://github.com/EmaSleal/call-copilot/commit/54c0a6a266889733ad18b25a2b3748ed07376fac))


### Bug Fixes

* **tui:** remove dead sync_category_embedding import from video/modal tabs ([0e3f7c8](https://github.com/EmaSleal/call-copilot/commit/0e3f7c850dfbd28a9b8d89a7d2d4c3b2fd3c97c4))

## [0.4.0](https://github.com/EmaSleal/call-copilot/compare/v0.3.0...v0.4.0) (2026-08-17)


### Features

* **db:** soft-delete + audit log for categories and video sessions ([20bbb17](https://github.com/EmaSleal/call-copilot/commit/20bbb17cdcf431564ea0c01480a4d1ef2239b46b))
* **installer:** port the stale-venv cleanup/retry to install.ps1 and install.sh ([4bc5e85](https://github.com/EmaSleal/call-copilot/commit/4bc5e8564ee353a5cb95c6638b39e4d7600b9e29))
* **rag,db:** soft-delete + audit log foundation for AI-agent CRUD ([f3327b6](https://github.com/EmaSleal/call-copilot/commit/f3327b6e8274d28286bd017c5f181fa11fcfd909))
* **rag:** sync Chroma vector deletes with SQL soft-deletes ([dd65f2f](https://github.com/EmaSleal/call-copilot/commit/dd65f2f48d36efe03e96faec091f402dcb35be68))


### Bug Fixes

* **updater:** sweep leftover venv after uninstall, not just on update ([84f5dab](https://github.com/EmaSleal/call-copilot/commit/84f5dab7a7d83a14230f83150d6e10b359abee40))

## [0.3.0](https://github.com/EmaSleal/call-copilot/compare/v0.2.0...v0.3.0) (2026-08-15)


### Features

* **updater:** auto-retry update once after cleaning a stale pipx venv ([f230ae0](https://github.com/EmaSleal/call-copilot/commit/f230ae012b650174327c449994f5a21fcf6da353))

## [0.2.0](https://github.com/EmaSleal/call-copilot/compare/v0.1.0...v0.2.0) (2026-08-15)


### Features

* add call-copilot --help / -h / help ([4dbff9d](https://github.com/EmaSleal/call-copilot/commit/4dbff9dd7cbef353e45f38db7162c54b4a38de82))
* add install.sh and `call-copilot update` ([6c90282](https://github.com/EmaSleal/call-copilot/commit/6c90282763ddd8f10db90a6263f6d62fa79e6a33))
* add project source code and documentation ([99c369f](https://github.com/EmaSleal/call-copilot/commit/99c369f85d317b113ce89355a3b98528e6022c05))
* add pyproject.toml with optional-dependency profiles ([6bdeebe](https://github.com/EmaSleal/call-copilot/commit/6bdeebe0f53819484fa5b20e54c2459315a38247))
* add version, check-update, doctor, uninstall commands ([e2f8612](https://github.com/EmaSleal/call-copilot/commit/e2f86125279f33b5760c9e0288a59a3b280f5240))
* add video transcriber, TUI, and database layer ([02cab89](https://github.com/EmaSleal/call-copilot/commit/02cab89754de294d2f2831d1b6dd0b242424ccfe))
* **audio:** add macOS BlackHole loopback support and Windows installer ([d7dd46d](https://github.com/EmaSleal/call-copilot/commit/d7dd46d0c53d70617a7f42082cf7b41d3f923f45)), closes [#4](https://github.com/EmaSleal/call-copilot/issues/4)
* **audio:** let the user pick which sink to capture for live calls ([58fa82a](https://github.com/EmaSleal/call-copilot/commit/58fa82a0124e49967ff1a56d5fdbed8bfaa03c24))
* **audio:** list WASAPI output devices on Windows, fix TUI overflow ([b92f52c](https://github.com/EmaSleal/call-copilot/commit/b92f52cb6c01c1338faddd2dc45747c03f606019))
* **categories:** add build_category_tree pure helper ([5a0123d](https://github.com/EmaSleal/call-copilot/commit/5a0123dc280ec70eee3db0a840097e3d21300aec))
* **categories:** wire hierarchy UI into CategoriesTab ([7853f2c](https://github.com/EmaSleal/call-copilot/commit/7853f2ccb662a1f694647cb85a96037b4c3f7734))
* **classifier:** add propose_parent_category for backfill parent naming ([8b858eb](https://github.com/EmaSleal/call-copilot/commit/8b858eb4cf4c1d32db3c97c1d2a63e7c509c870c))
* **config:** add .env writer preserving comments and untouched lines ([9c4fe78](https://github.com/EmaSleal/call-copilot/commit/9c4fe7831be7cff2ac101acab4054ea75c5fcac6))
* **config:** add canonical realtime defaults module ([85f1c0e](https://github.com/EmaSleal/call-copilot/commit/85f1c0ed8db2628d910c2ef526ba6dd9a5a6d804))
* content-aware trigger for call copilot ([c4e0aef](https://github.com/EmaSleal/call-copilot/commit/c4e0aeff0564e916c71ed5632ded104465bfc7c0))
* **core:** move persistent paths to ~/.call-copilot/ for installed use ([248a6ae](https://github.com/EmaSleal/call-copilot/commit/248a6aebe199f84892d41ff0d048db110f2bef2b))
* **db:** add call_segments table and session titles ([16a94dc](https://github.com/EmaSleal/call-copilot/commit/16a94dc523f1ac035e01d4ddd890014dbf00833a))
* **db:** add single-level category hierarchy + fix delete_category FK bug ([307a5cd](https://github.com/EmaSleal/call-copilot/commit/307a5cdfa653cdd0fcc6ce6b15df74f95508c8c1))
* **db:** add single-level category hierarchy + fix delete_category FK bug ([946f347](https://github.com/EmaSleal/call-copilot/commit/946f3478c709938899cfccbd7e4c85601281d1df))
* **db:** add unified_segments/unified_sessions views ([9dfd411](https://github.com/EmaSleal/call-copilot/commit/9dfd411103830ef459604c7e7de7960911129028))
* delete session files from data/videos on session deletion ([9e08868](https://github.com/EmaSleal/call-copilot/commit/9e088683e5d05196c38c46a01f886d9157bed35f))
* delete/reprocess session from modal and auto-refresh categories tab ([5455f1e](https://github.com/EmaSleal/call-copilot/commit/5455f1eb43a45d00b5645d8f98fc96216221d7b5))
* **historial:** edit fragment category via modal on row select ([b5e7b0d](https://github.com/EmaSleal/call-copilot/commit/b5e7b0d096cb98d5c48ba91504cd80011bb657f7))
* **historial:** global category reclassify tool, generalized from Video ([5d37b2d](https://github.com/EmaSleal/call-copilot/commit/5d37b2d6d6fdd4a05a89520d9ceeaada2d948a29))
* **installer:** pin install/update to the latest release tag, not main HEAD ([8838556](https://github.com/EmaSleal/call-copilot/commit/8838556e68255d4f518f629042a727bde62b66f9))
* **llm:** add live model discovery with static fallback ([986d364](https://github.com/EmaSleal/call-copilot/commit/986d3642605fbd6709d8d87a24bf8e6c6d48200a))
* **llm:** catch up per-profile response modes and RAG context ([f20aeaa](https://github.com/EmaSleal/call-copilot/commit/f20aeaa99da6543f4b792d520691c1cf804bfd95))
* merge short Whisper segments into complete-idea segments ([7587fac](https://github.com/EmaSleal/call-copilot/commit/7587fac02442a7203eba19b553c091e149f647ff))
* **pipeline:** add cooldown + near-duplicate dedup repetition guard ([9f84dd8](https://github.com/EmaSleal/call-copilot/commit/9f84dd8387b32e22cdeff5afa1b8059e9f0b3bbf))
* **processing:** add category hierarchy backfill tool ([2a94048](https://github.com/EmaSleal/call-copilot/commit/2a94048d902a24d65eeca348dba19196fef778b5))
* **processing:** add category_clustering pure module for hierarchy backfill ([6533647](https://github.com/EmaSleal/call-copilot/commit/65336479247d187bc70c576e6ad91bb3db99aab0))
* **processing:** add category_dedup fail-open shared entry point ([1b1be03](https://github.com/EmaSleal/call-copilot/commit/1b1be039a229ba01ab0c96b5ae2ba51c392d56e4))
* **processing:** catch up post-session idea extraction and RAG store ([fe2b3f1](https://github.com/EmaSleal/call-copilot/commit/fe2b3f1964389da8eb41aa06efa1699e3d002822))
* **profiles:** catch up conservative-mode heuristics and profile store ([39e6d2d](https://github.com/EmaSleal/call-copilot/commit/39e6d2d7b0d6954aedd2552c3d08ca3c5b4d1389))
* **rag:** add CategoriesStore Chroma-backed semantic store ([f768490](https://github.com/EmaSleal/call-copilot/commit/f768490469aa71220721860bdcd4015600d6885f))
* **rag:** add SegmentsSearchStore and by-ids lookups ([f476fee](https://github.com/EmaSleal/call-copilot/commit/f476feec9536c43e8fc460838256ac8c2bc96a40))
* **rag:** add semantic category dedup engine ([680730e](https://github.com/EmaSleal/call-copilot/commit/680730ed585eb2b52d3c43932f3bc042a360b05d))
* **rag:** index video/call segments for semantic search on write ([0f02b43](https://github.com/EmaSleal/call-copilot/commit/0f02b43cf924d5287cba915ecd113d9f6c11a134))
* **reclassify-modal:** wire dedup verdicts, drop cross-TUI import ([4a86a50](https://github.com/EmaSleal/call-copilot/commit/4a86a50a81b726ba284729b4835cdeb0f85efe8f))
* replace suggestions DataTable with SelectionList for multi-select ([e915e1b](https://github.com/EmaSleal/call-copilot/commit/e915e1b740f36689f8cbd242e5deacdb5c2e5ec6))
* session detail modal and processing feedback in VideoTab ([d0684fd](https://github.com/EmaSleal/call-copilot/commit/d0684fd4be2ae27f125368a8e5f47a9fc548490e))
* **settings:** add Settings panel for providers, keys, and models ([34adb0c](https://github.com/EmaSleal/call-copilot/commit/34adb0c276561ac6fb04917820c38d751f6cfc8c))
* **settings:** add tech-scout sync action to the Settings panel ([85fc3a4](https://github.com/EmaSleal/call-copilot/commit/85fc3a403fa021d06c7dda91ac882de763ccc55e))
* **settings:** expose SILENCE_THRESHOLD_MS in the Settings panel ([87699dc](https://github.com/EmaSleal/call-copilot/commit/87699dc791b0c5df1a75ceced80baaa888fbbd65))
* suggest new categories from uncategorized segments ([19379d1](https://github.com/EmaSleal/call-copilot/commit/19379d1274ee839979b5bae48cbc98d64de7987f))
* **tools-catalog:** add extraction, ingestion hook, and search (PR2) ([b811122](https://github.com/EmaSleal/call-copilot/commit/b811122c3e3746087ae8d4e307a0b3d7f52d9bb2))
* **tools-catalog:** add schema, DAOs, and ToolsCatalogStore (PR1) ([d25c47b](https://github.com/EmaSleal/call-copilot/commit/d25c47b9022835561cfabfdb1abc0604a1bc4c41))
* **tools-catalog:** extraction, ingestion hook, search, and Tools tab (PR2/2) ([aad4501](https://github.com/EmaSleal/call-copilot/commit/aad4501176c02a77837e088b6543e5d6789f482a))
* **tools-catalog:** schema, DAOs, and ToolsCatalogStore (PR1/2) ([1d7a405](https://github.com/EmaSleal/call-copilot/commit/1d7a40519c4aac298c7f1c7449394092b70260ff))
* **tui:** add semantic search button to the Buscar tab ([d976926](https://github.com/EmaSleal/call-copilot/commit/d9769265ae29f040f46372175321fbc041b5cf32))
* **tui:** add Tools tab to browse and search the tools catalog ([cd5c41b](https://github.com/EmaSleal/call-copilot/commit/cd5c41b5ae86b6a49f6a6c7681b0a8e5073605da))
* **tui:** catch up profile management, RAG context, and processing UI ([9260173](https://github.com/EmaSleal/call-copilot/commit/9260173d85b51635643d6560b5c2eba5921dbbeb))
* **tui:** unify Historial tab across video and call sessions ([5253eba](https://github.com/EmaSleal/call-copilot/commit/5253ebaade3538ffd4ddabb5074ec1d326f10db8))
* **tui:** wire category hierarchy UI + dedup verdicts ([c9148c2](https://github.com/EmaSleal/call-copilot/commit/c9148c2f9b6e1eb97f26d82232da07e8268739fc))
* **tui:** wire live model discovery into the profile model selector ([c9487d9](https://github.com/EmaSleal/call-copilot/commit/c9487d9b46a967e41764adf68b37d38e6bfdee7a))
* **video:** wire dedup verdicts into suggestion flow, drop partition helper ([fb4ca26](https://github.com/EmaSleal/call-copilot/commit/fb4ca268c9277619c593af91185ce6d33d10fe1d))


### Bug Fixes

* add packaging as a base dependency ([5267521](https://github.com/EmaSleal/call-copilot/commit/526752145125e84069504726b4be796ee2d13426))
* bring PR2 (extraction, hook, search, Tools tab) into linux-support ([42659a6](https://github.com/EmaSleal/call-copilot/commit/42659a6c7812f33ed689f0fba1d10d8751fe1a36))
* **deps:** unpin PyAudioWPatch exact version, allow &gt;=0.2.12.8 ([4e7083f](https://github.com/EmaSleal/call-copilot/commit/4e7083f069aed9f8bf7baa44beac90decaa2bea6))
* improve segment merging logic to avoid mid-idea cuts and enhance boundary detection ([837247a](https://github.com/EmaSleal/call-copilot/commit/837247ab911a5919ddb0880fc44c1be30e6bb556))
* **llm:** honor per-profile model override, validate against backend ([9ff7e1f](https://github.com/EmaSleal/call-copilot/commit/9ff7e1f6254188a75ee79d4ae22e6a9a562e760f))
* **main:** use PulseAudio on Linux, thread OpenAI client for RAG ([7bed732](https://github.com/EmaSleal/call-copilot/commit/7bed7323245047cd27d27fae5c05098e38235d24))
* only reduce trigger delay for questions, not all sentence ends ([a1502d9](https://github.com/EmaSleal/call-copilot/commit/a1502d9c12eded56811d97e0309179e958d8eaed))
* **rag:** guard ToolsCatalogStore.search() without an OpenAI client ([2959ef3](https://github.com/EmaSleal/call-copilot/commit/2959ef321a7828f93588b7d7f35494089826317c))
* **rag:** make chromadb a lazy, optional dependency ([bf86f98](https://github.com/EmaSleal/call-copilot/commit/bf86f98e7e30e1cf6250179473469ac4e6dcd127))
* read install.sh prompts from /dev/tty, not stdin ([541135c](https://github.com/EmaSleal/call-copilot/commit/541135c9e2861a5cf4d9fd1f312312d3c84a4216))
* remove stale btn-analyze-others reference in _analyze_others ([5a5cbe1](https://github.com/EmaSleal/call-copilot/commit/5a5cbe12094ea242ede1117a2b4d9193998f35e1))
* replace `pipx install --force` with uninstall-then-install ([8c75654](https://github.com/EmaSleal/call-copilot/commit/8c756541fd48039a2c16b16abdd91c4465dee4bb))
* rewrite install.sh as POSIX sh — no bash required ([17ac365](https://github.com/EmaSleal/call-copilot/commit/17ac3651f7c21fc2f5e871a1cd0c793452297eb4))
* set cursor_type=row on sessions table to trigger RowSelected event ([45b4720](https://github.com/EmaSleal/call-copilot/commit/45b47203857f293d08995e5c4578cb33854af0f0))
* set cursor_type=row on suggestions table ([ca9f739](https://github.com/EmaSleal/call-copilot/commit/ca9f7390844c4030044953cb5fd764cae12da9e1))
* Silero VAD trust_repo, drop dead code, widen Whisper buffer ([df6bdf7](https://github.com/EmaSleal/call-copilot/commit/df6bdf7084e38382af60ac0d60a0f6b28423c0a0))
* smarter segment merging using clause breaks and backward scan ([9ea8cbe](https://github.com/EmaSleal/call-copilot/commit/9ea8cbea50bcdc3f302e7df049551265d33994bc))
* **stt:** align Deepgram provider with official streaming API guidance ([81ca8c5](https://github.com/EmaSleal/call-copilot/commit/81ca8c563671eb46cf875aefbe4f0649efbda605))
* surface LLM errors and fix streaming output in call copilot ([f8caaf3](https://github.com/EmaSleal/call-copilot/commit/f8caaf31c4634bc0eba0deb1c4629c4fbb73cc34))
* **tui:** pin explicit height on audio-sink-row/call-buttons, stop relying on auto ([014e63e](https://github.com/EmaSleal/call-copilot/commit/014e63e943bc2fb06155153e396c88717f12bdfe))
* **tui:** refresh Categorías/Historial data when the tab becomes active ([f16813b](https://github.com/EmaSleal/call-copilot/commit/f16813b0b0839814aaed8750f8d4328697f53780))
* **updater:** point call-copilot update at main, not the stale linux-support branch ([741a666](https://github.com/EmaSleal/call-copilot/commit/741a666cccec2ecf50e50a037dde8c909746753f))
* use debounce instead of instant trigger on content boundary ([a6b2745](https://github.com/EmaSleal/call-copilot/commit/a6b274584b8439e3db2b1643d0db21ffd4c89c53))
* **video:** ask category suggester for general, reusable descriptions ([b3ccb27](https://github.com/EmaSleal/call-copilot/commit/b3ccb2763dbfd8dbe90df768539b73a249a621d3))
* **video:** resolve yt-dlp/ffmpeg from the venv instead of PATH ([45c1ed0](https://github.com/EmaSleal/call-copilot/commit/45c1ed04dede687cc1874731560e06ca50dedd91))
* **video:** stop crash on duplicate category name, add reclassify ([5500442](https://github.com/EmaSleal/call-copilot/commit/550044275abeefd319a9e0c9e4d5924963436444))


### Performance Improvements

* batch segment classification and add Ollama backend ([552ea9c](https://github.com/EmaSleal/call-copilot/commit/552ea9c7e0a5162008fd608cdda8faa15121fd1c))


### Documentation

* add promo banner image to README ([52c95f3](https://github.com/EmaSleal/call-copilot/commit/52c95f37a33ffbd0294583404957af10cbe4fa32))
* add Tools tab and tools/tool_mentions to README ([9ba6e6c](https://github.com/EmaSleal/call-copilot/commit/9ba6e6c3154d6d78addca4a38ad0c8216df62e0b))
* document pipx install and CLI commands in README ([02cd8ed](https://github.com/EmaSleal/call-copilot/commit/02cd8ed33c1363e88c7616a6e67bf6ca99c2b486))
* rewrite README to match the current TUI-based architecture ([ff3a330](https://github.com/EmaSleal/call-copilot/commit/ff3a33070e4a37f936fa597da4121f2706748677))
