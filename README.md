# HyperAgent

**Goal**: Build a static-analysis microservice for Hyperscope.

## Features
1. Receive sample → inspect with DIE
2. Classify language/arch/packer
3. Select disassembler automatically
4. MCP controls tools (Ghidra, Rizin, ILSpy)
5. Produce normalized JSON output
6. Provide API for Hyperscope
7. Full structured logging

## Pipeline
Ingestor → DIE → Strategy → MCP → Logger → JSON builder

## Development Roadmap & Status

### Phase 1: Create skeleton + FastAPI + basic schemas [COMPLETED]
- [x] Set up project structure
- [x] Install dependencies (FastAPI, Uvicorn, etc.)
- [x] Create main application entry point
- [x] Define basic Pydantic schemas
- [x] Create basic endpoint to receive sample

### Phase 2: DIE wrapper (CLI call + parser) [COMPLETED]
- [x] Implement DIE wrapper function
- [x] Parse DIE output (Text/JSON)
- [x] Integrate DIE wrapper into analysis endpoint

### Phase 3: Strategy selector (YAML-based rule engine) [TODO]
- [ ] Define strategy rules (YAML)
- [ ] Implement strategy selector logic based on DIE output
- [ ] Select appropriate tools (Ghidra, Rizin, ILSpy)

### Phase 4: MCP adapters (ghidra, rizin, ilspy) [TODO]
- [ ] Implement Ghidra adapter
- [ ] Implement Rizin adapter
- [ ] Implement ILSpy adapter
- [ ] Standardize tool outputs

### Phase 5: Static pipeline orchestrator [TODO]
- [ ] Orchestrate the flow: Ingest → DIE → Strategy → Tool → Output
- [ ] Error handling and fallback mechanisms

### Phase 6: API integration [TODO]
- [ ] Finalize API endpoints for Hyperscope
- [ ] Ensure proper response format

### Phase 7: Optional [TODO]
- [ ] Caching mechanism
- [ ] Unpackers integration
- [ ] Extended heuristics

## Deliverables
- JSON output format
- Log event format
- Example analysis job