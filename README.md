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

## Installation for development

### Run the microservice
```bash
# Create virtual environment if u want :v
python -m venv venv
venv\Scripts\activate (optional)

pip install -r requirements.txt

# Run the app
uvicorn app.main:app --port 8000 --reload
```

### Run the tests
> Test functions with test_*.py files. Before running the tests, make sure to run the microservice.

## Development Roadmap & Status

### Phase 1: Create skeleton + FastAPI + basic schemas [COMPLETED]
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