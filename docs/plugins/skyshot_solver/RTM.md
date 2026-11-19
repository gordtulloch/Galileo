# Skyshot Solver Plugin — RTM (Requirements Traceability Matrix)

| | |
|---|---|
| **Project** | Galileo — Skyshot Solver Plugin |
| **Document** | RTM (Requirements Traceability Matrix), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-11-19 |
| **Upstream documents** | [PSD](PSD.md), [SRS](SRS.md), [SDD](SDD.md) |
| **Parent project** | [Galileo Core RTM](../../RTM.md) |

---

Test Case IDs follow `TC-<requirement ID>`. Tests are in `Galileo-Plugins/skyshot_solver/tests/test_skyshot.py`; they run with no network and no Skyshot program (downloads are served from memory and the program is replaced by a fake process). An opt-in test (`SKYSHOT_REAL_DIR`, `TC-SKY-010`) runs a real Skyshot build against Skyshot's synthetic demo. **Not covered:** a real frame and the full-sky index; any platform but Windows; the CI workflow itself, which has not yet been run.

**Coverage:** 11 requirements, 100% mapped to an SDD module; `SKY-100` is verified by inspection of the CI workflow (it runs only on GitHub), the rest by tests.

| SRS ID | Priority | SDD Component | Verification | Test Case |
|---|---|---|---|---|
| `SKY-010` | P2 | SDD §2 `backend` | Test | `TC-SKY-010` |
| `SKY-020` | P2 | SDD §2 `backend` (`result_from_wcs`) | Test | `TC-SKY-020` |
| `SKY-030` | P2 | SDD §2 `data` (`parse_release`) | Test | `TC-SKY-030` |
| `SKY-040` | P2 | SDD §2 `data` (`install_preset`, `unpack_archive`) | Test | `TC-SKY-040` |
| `SKY-050` | P2 | SDD §2 `data` (`download_artifact`) | Test | `TC-SKY-050` |
| `SKY-060` | P2 | SDD §2 `ui` | Test | `TC-SKY-060` |
| `SKY-070` | P2 | SDD §2 `settings`, `backend` | Test | `TC-SKY-070` |
| `SKY-080` | P2 | SDD §2 `engine`, `engine_builds`; §3 pinned hashes | Test | `TC-SKY-080` |
| `SKY-090` | P2 | SDD §2 `engine`, `backend` (`find_executable`) | Test | `TC-SKY-090` |
| `SKY-100` | P2 | SDD §3 build provenance (`skyshot-engine.yml`) | Inspection | n/a (runs in CI) |
| `SKY-110` | P2 | SDD §2 `credits`, `ui`, `data` (`_check_bundle`), `engine`; core `THIRD_PARTY_NOTICES.md` | Test | `TC-SKY-110` |
