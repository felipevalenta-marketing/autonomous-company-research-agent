import { expr, ifElse, newCredential, node, sticky, trigger, workflow } from '@n8n/workflow-sdk';

const startResearchDemo = trigger({
  type: 'n8n-nodes-base.manualTrigger',
  version: 1,
  config: {
    name: 'Start Research Demo',
    position: [200, 180],
  },
  output: [{}],
});

const prepareDemoRequest = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Prepare Demo Request',
    position: [450, 180],
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'source', name: 'source', value: 'manual_demo', type: 'string' },
          { id: 'company', name: 'company', value: 'Apple Inc.', type: 'string' },
          { id: 'ticker', name: 'ticker', value: 'AAPL', type: 'string' },
          { id: 'cik', name: 'cik', value: '0000320193', type: 'string' },
          {
            id: 'query',
            name: 'query',
            value: "Analyze the company's recent financial performance and strategic risks",
            type: 'string',
          },
        ],
      },
    },
  },
  output: [
    {
      source: 'manual_demo',
      company: 'Apple Inc.',
      ticker: 'AAPL',
      cik: '0000320193',
      query: "Analyze the company's recent financial performance and strategic risks",
    },
  ],
});

const researchApi = trigger({
  type: 'n8n-nodes-base.webhook',
  version: 2.1,
  config: {
    name: 'Research API',
    position: [200, 480],
    parameters: {
      httpMethod: 'POST',
      path: 'company-research',
      responseMode: 'lastNode',
    },
  },
  output: [
    {
      body: {
        company: 'Apple Inc.',
        ticker: 'AAPL',
        cik: '0000320193',
        query: "Analyze the company's recent financial performance and strategic risks",
      },
    },
  ],
});

const normalizeWebhookRequest = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Normalize Webhook Request',
    position: [450, 480],
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'source', name: 'source', value: 'webhook', type: 'string' },
          { id: 'company', name: 'company', value: expr('{{ $json.body?.company ?? $json.company ?? "" }}'), type: 'string' },
          { id: 'ticker', name: 'ticker', value: expr('{{ $json.body?.ticker ?? $json.ticker ?? "" }}'), type: 'string' },
          { id: 'cik', name: 'cik', value: expr('{{ $json.body?.cik ?? $json.cik ?? "" }}'), type: 'string' },
          { id: 'query', name: 'query', value: expr('{{ $json.body?.query ?? $json.query ?? "" }}'), type: 'string' },
        ],
      },
    },
  },
  output: [
    {
      source: 'webhook',
      company: 'Apple Inc.',
      ticker: 'AAPL',
      cik: '0000320193',
      query: "Analyze the company's recent financial performance and strategic risks",
    },
  ],
});

const validateResearchInput = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Validate Research Input',
    position: [720, 320],
    parameters: {
      mode: 'manual',
      includeOtherFields: true,
      assignments: {
        assignments: [
          {
            id: 'company-valid',
            name: 'company_valid',
            value: expr('{{ typeof $json.company === "string" && $json.company.trim().length > 0 }}'),
            type: 'boolean',
          },
          {
            id: 'ticker-valid',
            name: 'ticker_valid',
            value: expr('{{ typeof $json.ticker === "string" && $json.ticker.trim().length > 0 }}'),
            type: 'boolean',
          },
          {
            id: 'cik-valid',
            name: 'cik_valid',
            value: expr('{{ typeof $json.cik === "string" && /^[0-9]+$/.test($json.cik.trim()) }}'),
            type: 'boolean',
          },
          {
            id: 'query-valid',
            name: 'query_valid',
            value: expr('{{ typeof $json.query === "string" && $json.query.trim().length > 0 }}'),
            type: 'boolean',
          },
          {
            id: 'input-valid',
            name: 'input_valid',
            value: expr('{{ typeof $json.company === "string" && $json.company.trim().length > 0 && typeof $json.ticker === "string" && $json.ticker.trim().length > 0 && typeof $json.cik === "string" && /^[0-9]+$/.test($json.cik.trim()) && typeof $json.query === "string" && $json.query.trim().length > 0 }}'),
            type: 'boolean',
          },
          {
            id: 'normalized-cik',
            name: 'normalized_cik',
            value: expr('{{ typeof $json.cik === "string" && /^[0-9]+$/.test($json.cik.trim()) ? String(parseInt($json.cik.trim(), 10)).padStart(10, "0") : "" }}'),
            type: 'string',
          },
        ],
      },
    },
  },
  output: [
    {
      source: 'manual_demo',
      company: 'Apple Inc.',
      ticker: 'AAPL',
      cik: '0000320193',
      query: "Analyze the company's recent financial performance and strategic risks",
      company_valid: true,
      ticker_valid: true,
      cik_valid: true,
      query_valid: true,
      input_valid: true,
      normalized_cik: '0000320193',
    },
  ],
});

const inputValidAndComplete = ifElse({
  version: 2.2,
  config: {
    name: 'Input Valid and Complete?',
    position: [980, 320],
    parameters: {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'strict' },
        conditions: [
          {
            leftValue: expr('{{ $json.input_valid ? "true" : "false" }}'),
            operator: { type: 'string', operation: 'equals' },
            rightValue: 'true',
          },
        ],
        combinator: 'and',
      },
    },
  },
  output: [
    {
      input_valid: true,
    },
  ],
});

const validationError = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Validation Error',
    position: [1280, 540],
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'status', name: 'status', value: 'failed', type: 'string' },
          { id: 'stage', name: 'stage', value: 'input_validation', type: 'string' },
          { id: 'error-code', name: 'error_code', value: 'INVALID_RESEARCH_REQUEST', type: 'string' },
          {
            id: 'message',
            name: 'message',
            value: 'Company, ticker, CIK and research query are required.',
            type: 'string',
          },
          { id: 'source', name: 'source', value: expr('{{ $json.source ?? "" }}'), type: 'string' },
          { id: 'timestamp', name: 'timestamp', value: expr('{{ $now.toISO() }}'), type: 'string' },
          {
            id: 'errors',
            name: 'errors',
            value: expr('{{ { category: "validation", code: "INVALID_RESEARCH_REQUEST", message: "Company, ticker, CIK and research query are required." } }}'),
            type: 'object',
          },
        ],
      },
    },
  },
  output: [
    {
      status: 'failed',
      stage: 'input_validation',
      error_code: 'INVALID_RESEARCH_REQUEST',
      message: 'Company, ticker, CIK and research query are required.',
      source: 'manual_demo',
      timestamp: '2026-08-01T12:00:00.000Z',
      errors: {
        category: 'validation',
        code: 'INVALID_RESEARCH_REQUEST',
        message: 'Company, ticker, CIK and research query are required.',
      },
    },
  ],
});

const runAutonomousResearchAgent = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.4,
  config: {
    name: 'Run Autonomous Research Agent',
    position: [1280, 220],
    parameters: {
      method: 'POST',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpHeaderAuth',
      url: 'https://autonomous-company-research-agent-production.up.railway.app/research',
      sendBody: true,
      contentType: 'json',
      specifyBody: 'json',
      jsonBody: expr('{{ { company: $json.company, ticker: $json.ticker, cik: $json.normalized_cik, query: $json.query } }}'),
      responseFormat: 'json',
      timeout: 120000,
      fullResponse: true,
      ignoreResponseCode: true,
    },
    credentials: {
      httpHeaderAuth: newCredential('Autonomous Research Agent API'),
    },
  },
  output: [
    {
      statusCode: 200,
      body: {
        research_query: "Analyze the company's recent financial performance and strategic risks",
        resolved_company: {
          company_name: 'Apple Inc.',
          ticker: 'AAPL',
          cik: '0000320193',
        },
        summary: 'Apple Inc. posted strong cash flow and margin stability, while facing hardware concentration and China exposure risks.',
        executive_summary: 'Apple remains financially resilient but exposed to concentration and strategic execution risks.',
        evidence_bundle: {
          evidence_count: 1,
          source_count: 1,
          document_count: 1,
          evidence: [],
        },
        sources: [
          {
            title: 'Apple 10-K',
            url: 'https://example.com/apple-10k',
          },
        ],
        documents: [
          {
            title: 'Apple Annual Filing',
            id: 'doc-1',
          },
        ],
        metrics: {
          evidence_count: 1,
          source_count: 1,
          document_count: 1,
        },
        status: 'success',
        timestamp: '2026-08-01T12:00:00.000Z',
        errors: null,
      },
    },
  ],
});

const normalizeAgentResponse = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Normalize Agent Response',
    position: [1560, 220],
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          {
            id: 'http-status',
            name: 'http_status',
            value: expr('{{ Number($json.statusCode ?? $json.status ?? 0) }}'),
            type: 'number',
          },
          {
            id: 'research-query',
            name: 'research_query',
            value: expr('{{ ($json.body ?? $json.data ?? $json).research_query ?? "" }}'),
            type: 'string',
          },
          {
            id: 'resolved-company',
            name: 'resolved_company',
            value: expr('{{ ($json.body ?? $json.data ?? $json).resolved_company ?? {} }}'),
            type: 'object',
          },
          {
            id: 'summary',
            name: 'summary',
            value: expr('{{ ($json.body ?? $json.data ?? $json).summary ?? "" }}'),
            type: 'string',
          },
          {
            id: 'executive-summary',
            name: 'executive_summary',
            value: expr('{{ ($json.body ?? $json.data ?? $json).executive_summary ?? "" }}'),
            type: 'string',
          },
          {
            id: 'evidence-bundle',
            name: 'evidence_bundle',
            value: expr('{{ ($json.body ?? $json.data ?? $json).evidence_bundle ?? {} }}'),
            type: 'object',
          },
          {
            id: 'sources',
            name: 'sources',
            value: expr('{{ ($json.body ?? $json.data ?? $json).sources ?? (($json.body ?? $json.data ?? $json).evidence_bundle?.sources ?? []) }}'),
            type: 'array',
          },
          {
            id: 'documents',
            name: 'documents',
            value: expr('{{ ($json.body ?? $json.data ?? $json).documents ?? (($json.body ?? $json.data ?? $json).evidence_bundle?.documents ?? []) }}'),
            type: 'array',
          },
          {
            id: 'metrics',
            name: 'metrics',
            value: expr('{{ { evidence_count: Number((($json.body ?? $json.data ?? $json).evidence_bundle?.evidence_count ?? (($json.body ?? $json.data ?? $json).metrics?.evidence_count ?? 0))), source_count: Number((($json.body ?? $json.data ?? $json).evidence_bundle?.source_count ?? (($json.body ?? $json.data ?? $json).metrics?.source_count ?? 0))), document_count: Number((($json.body ?? $json.data ?? $json).evidence_bundle?.document_count ?? (($json.body ?? $json.data ?? $json).metrics?.document_count ?? 0))) } }}'),
            type: 'object',
          },
          {
            id: 'timestamp',
            name: 'timestamp',
            value: expr('{{ ($json.body ?? $json.data ?? $json).timestamp ?? $now.toISO() }}'),
            type: 'string',
          },
          {
            id: 'success',
            name: 'success',
            value: expr('{{ Number($json.statusCode ?? $json.status ?? 0) >= 200 && Number($json.statusCode ?? $json.status ?? 0) < 300 && Boolean((($json.body ?? $json.data ?? $json).resolved_company?.company_name ?? ($json.body ?? $json.data ?? $json).resolved_company?.name ?? ($json.body ?? $json.data ?? $json).resolved_company?.company)) && Boolean(($json.body ?? $json.data ?? $json).evidence_bundle) && Array.isArray(($json.body ?? $json.data ?? $json).evidence_bundle?.evidence) }}'),
            type: 'boolean',
          },
          {
            id: 'error-code',
            name: 'error_code',
            value: expr('{{ ($json.body ?? $json.data ?? $json).error_code ?? (($json.body ?? $json.data ?? $json).errors?.code ?? null) }}'),
            type: 'string',
          },
          {
            id: 'error-message',
            name: 'error_message',
            value: expr('{{ ($json.body ?? $json.data ?? $json).message ?? (($json.body ?? $json.data ?? $json).error_message ?? (($json.body ?? $json.data ?? $json).errors?.message ?? null)) }}'),
            type: 'string',
          },
          {
            id: 'error-category',
            name: 'error_category',
            value: expr('{{ Number($json.statusCode ?? $json.status ?? 0) >= 200 && Number($json.statusCode ?? $json.status ?? 0) < 300 && Boolean((($json.body ?? $json.data ?? $json).resolved_company?.company_name ?? ($json.body ?? $json.data ?? $json).resolved_company?.name ?? ($json.body ?? $json.data ?? $json).resolved_company?.company)) && Boolean(($json.body ?? $json.data ?? $json).evidence_bundle) && Array.isArray(($json.body ?? $json.data ?? $json).evidence_bundle?.evidence) ? "success" : (/(timeout|timed out|etimedout|timeout exceeded)/i.test(String(($json.body ?? $json.data ?? $json).message ?? (($json.body ?? $json.data ?? $json).error_message ?? (($json.body ?? $json.data ?? $json).errors?.message ?? "")))) || [408, 504].includes(Number($json.statusCode ?? $json.status ?? 0)) ? "timeout" : (Number($json.statusCode ?? $json.status ?? 0) >= 200 && Number($json.statusCode ?? $json.status ?? 0) < 300 ? "python" : (Number($json.statusCode ?? $json.status ?? 0) >= 400 && Number($json.statusCode ?? $json.status ?? 0) < 600 ? "python" : "unexpected"))) }}'),
            type: 'string',
          },
          {
            id: 'errors',
            name: 'errors',
            value: expr('{{ { category: Number($json.statusCode ?? $json.status ?? 0) >= 200 && Number($json.statusCode ?? $json.status ?? 0) < 300 && Boolean((($json.body ?? $json.data ?? $json).resolved_company?.company_name ?? ($json.body ?? $json.data ?? $json).resolved_company?.name ?? ($json.body ?? $json.data ?? $json).resolved_company?.company)) && Boolean(($json.body ?? $json.data ?? $json).evidence_bundle) && Array.isArray(($json.body ?? $json.data ?? $json).evidence_bundle?.evidence) ? null : (/(timeout|timed out|etimedout|timeout exceeded)/i.test(String(($json.body ?? $json.data ?? $json).message ?? (($json.body ?? $json.data ?? $json).error_message ?? (($json.body ?? $json.data ?? $json).errors?.message ?? "")))) || [408, 504].includes(Number($json.statusCode ?? $json.status ?? 0)) ? "timeout" : (Number($json.statusCode ?? $json.status ?? 0) >= 200 && Number($json.statusCode ?? $json.status ?? 0) < 300 ? "python" : (Number($json.statusCode ?? $json.status ?? 0) >= 400 && Number($json.statusCode ?? $json.status ?? 0) < 600 ? "python" : "unexpected"))), code: ($json.body ?? $json.data ?? $json).error_code ?? (($json.body ?? $json.data ?? $json).errors?.code ?? null), message: ($json.body ?? $json.data ?? $json).message ?? (($json.body ?? $json.data ?? $json).error_message ?? (($json.body ?? $json.data ?? $json).errors?.message ?? null)), http_status: Number($json.statusCode ?? $json.status ?? 0) } }}'),
            type: 'object',
          },
        ],
      },
    },
  },
  output: [
    {
      http_status: 200,
      research_query: "Analyze the company's recent financial performance and strategic risks",
      resolved_company: {
        company_name: 'Apple Inc.',
        ticker: 'AAPL',
        cik: '0000320193',
      },
      summary: 'Apple Inc. posted strong cash flow and margin stability, while facing hardware concentration and China exposure risks.',
      executive_summary: 'Apple remains financially resilient but exposed to concentration and strategic execution risks.',
      evidence_bundle: {
        evidence_count: 1,
        source_count: 1,
        document_count: 1,
        evidence: [],
      },
      sources: [
        {
          title: 'Apple 10-K',
          url: 'https://example.com/apple-10k',
        },
      ],
      documents: [
        {
          title: 'Apple Annual Filing',
          id: 'doc-1',
        },
      ],
      metrics: {
        evidence_count: 1,
        source_count: 1,
        document_count: 1,
      },
      timestamp: '2026-08-01T12:00:00.000Z',
      success: true,
      error_code: null,
      error_message: null,
      error_category: 'success',
      errors: {
        category: null,
        code: null,
        message: null,
        http_status: 200,
      },
    },
  ],
});

const researchSuccessful = ifElse({
  version: 2.2,
  config: {
    name: 'Research Successful?',
    position: [1830, 220],
    parameters: {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'strict' },
        conditions: [
          {
            leftValue: expr('{{ $json.success ? "true" : "false" }}'),
            operator: { type: 'string', operation: 'equals' },
            rightValue: 'true',
          },
        ],
        combinator: 'and',
      },
    },
  },
  output: [
    {
      success: true,
    },
  ],
});

const timeoutCheck = ifElse({
  version: 2.2,
  config: {
    name: 'Timeout?',
    position: [2100, 220],
    parameters: {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'strict' },
        conditions: [
          {
            leftValue: expr('{{ $json.error_category }}'),
            operator: { type: 'string', operation: 'equals' },
            rightValue: 'timeout',
          },
        ],
        combinator: 'and',
      },
    },
  },
  output: [
    {
      error_category: 'timeout',
    },
  ],
});

const pythonErrorCheck = ifElse({
  version: 2.2,
  config: {
    name: 'Python Error?',
    position: [2100, 360],
    parameters: {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'strict' },
        conditions: [
          {
            leftValue: expr('{{ $json.error_category }}'),
            operator: { type: 'string', operation: 'equals' },
            rightValue: 'python',
          },
        ],
        combinator: 'and',
      },
    },
  },
  output: [
    {
      error_category: 'python',
    },
  ],
});

const buildResearchSummary = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Build Research Summary',
    position: [2100, 100],
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'status', name: 'status', value: 'completed', type: 'string' },
          { id: 'timestamp', name: 'timestamp', value: expr('{{ $json.timestamp }}'), type: 'string' },
          {
            id: 'company',
            name: 'company',
            value: expr('{{ (() => { const company = $json.resolved_company ?? {}; return { name: company.company_name ?? company.name ?? company.company ?? "", ticker: company.ticker ?? "", cik: company.cik ?? "" }; })() }}'),
            type: 'object',
          },
          { id: 'research-query', name: 'research_query', value: expr('{{ $json.research_query }}'), type: 'string' },
          {
            id: 'summary',
            name: 'summary',
            value: expr('{{ { evidence_count: Number($json.evidence_bundle?.evidence_count ?? $json.metrics?.evidence_count ?? 0), source_count: Number($json.evidence_bundle?.source_count ?? $json.metrics?.source_count ?? 0), document_count: Number($json.evidence_bundle?.document_count ?? $json.metrics?.document_count ?? 0) } }}'),
            type: 'object',
          },
          {
            id: 'key-evidence',
            name: 'key_evidence',
            value: expr('{{ (() => { const evidence = Array.isArray($json.evidence_bundle?.evidence) ? $json.evidence_bundle.evidence.slice() : []; return evidence.sort((left, right) => { const scoreDiff = Number(right.similarity_score ?? 0) - Number(left.similarity_score ?? 0); if (scoreDiff !== 0) { return scoreDiff; } return String(left.document_id ?? "").localeCompare(String(right.document_id ?? "")) || String(left.chunk_id ?? "").localeCompare(String(right.chunk_id ?? "")) || String(left.source_id ?? "").localeCompare(String(right.source_id ?? "")); }).slice(0, 3).map((item, index) => ({ rank: index + 1, text: String(item.text ?? ""), similarity_score: Number(item.similarity_score ?? 0), source_url: String(item.source_url ?? ""), document_id: String(item.document_id ?? ""), chunk_id: String(item.chunk_id ?? ""), source_id: String(item.source_id ?? "") })); })() }}'),
            type: 'array',
          },
          {
            id: 'markdown',
            name: 'markdown',
            value: expr('{{ (() => { const body = $json; const company = body.resolved_company ?? {}; const companyName = company.company_name ?? company.name ?? company.company ?? ""; const ticker = company.ticker ?? ""; const cik = company.cik ?? ""; const researchQuery = body.research_query ?? ""; const summary = { evidence_count: Number(body.evidence_bundle?.evidence_count ?? body.metrics?.evidence_count ?? 0), source_count: Number(body.evidence_bundle?.source_count ?? body.metrics?.source_count ?? 0), document_count: Number(body.evidence_bundle?.document_count ?? body.metrics?.document_count ?? 0) }; const evidence = Array.isArray(body.evidence_bundle?.evidence) ? body.evidence_bundle.evidence.slice() : []; const sortedEvidence = evidence.sort((left, right) => { const scoreDiff = Number(right.similarity_score ?? 0) - Number(left.similarity_score ?? 0); if (scoreDiff !== 0) { return scoreDiff; } return String(left.document_id ?? "").localeCompare(String(right.document_id ?? "")) || String(left.chunk_id ?? "").localeCompare(String(right.chunk_id ?? "")) || String(left.source_id ?? "").localeCompare(String(right.source_id ?? "")); }).slice(0, 3); const companyLine = companyName + (ticker ? " (" + ticker + ")" : "") + (cik ? " [CIK " + cik + "]" : ""); const lines = ["# Company Research Result", "", "## Company", companyLine, "", "## Research Query", researchQuery || "N/A", "", "## Retrieval Summary", "- Evidence records: " + summary.evidence_count, "- Sources: " + summary.source_count, "- Documents: " + summary.document_count]; if (sortedEvidence.length > 0) { lines.push("", "## Key Evidence"); sortedEvidence.forEach((item, index) => { const title = item.source_id ? String(item.source_id) : "Evidence " + (index + 1); lines.push("", "### " + (index + 1) + ". " + title, String(item.text ?? ""), "", "Similarity: " + Number(item.similarity_score ?? 0).toFixed(3), item.source_url ? "Source: " + String(item.source_url) : "Source: N/A"); }); } return lines.join("\\n"); })() }}'),
            type: 'string',
          },
        ],
      },
    },
  },
  output: [
    {
      status: 'completed',
      timestamp: '2026-08-01T12:00:00.000Z',
      company: {
        name: 'Apple Inc.',
        ticker: 'AAPL',
        cik: '0000320193',
      },
      research_query: "Analyze the company's recent financial performance and strategic risks",
      summary: {
        evidence_count: 0,
        source_count: 0,
        document_count: 0,
      },
      key_evidence: [],
      markdown: '# Company Research Result\n\n## Company\nApple Inc. (AAPL) [CIK 0000320193]\n\n## Research Query\nAnalyze the company\'s recent financial performance and strategic risks\n\n## Retrieval Summary\n- Evidence records: 0\n- Sources: 0\n- Documents: 0',
    },
  ],
});

const researchResult = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Research Result',
    position: [2380, 100],
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'status', name: 'status', value: expr('{{ $json.status }}'), type: 'string' },
          { id: 'timestamp', name: 'timestamp', value: expr('{{ $json.timestamp }}'), type: 'string' },
          { id: 'company', name: 'company', value: expr('{{ $json.company }}'), type: 'object' },
          { id: 'research-query', name: 'research_query', value: expr('{{ $json.research_query }}'), type: 'string' },
          { id: 'summary', name: 'summary', value: expr('{{ $json.summary }}'), type: 'object' },
          { id: 'key-evidence', name: 'key_evidence', value: expr('{{ $json.key_evidence }}'), type: 'array' },
          { id: 'markdown', name: 'markdown', value: expr('{{ $json.markdown }}'), type: 'string' },
        ],
      },
    },
  },
  output: [
    {
      status: 'completed',
      timestamp: '2026-08-01T12:00:00.000Z',
      company: {
        name: 'Apple Inc.',
        ticker: 'AAPL',
        cik: '0000320193',
      },
      research_query: "Analyze the company's recent financial performance and strategic risks",
      summary: {
        evidence_count: 0,
        source_count: 0,
        document_count: 0,
      },
      key_evidence: [],
      markdown: '# Company Research Result\n\n## Company\nApple Inc. (AAPL) [CIK 0000320193]\n\n## Research Query\nAnalyze the company\'s recent financial performance and strategic risks\n\n## Retrieval Summary\n- Evidence records: 0\n- Sources: 0\n- Documents: 0',
    },
  ],
});

const pythonError = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Python Error',
    position: [2380, 300],
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'status', name: 'status', value: 'failed', type: 'string' },
          { id: 'stage', name: 'stage', value: 'research_execution', type: 'string' },
          { id: 'timestamp', name: 'timestamp', value: expr('{{ $json.timestamp ?? $now.toISO() }}'), type: 'string' },
          { id: 'http-status', name: 'http_status', value: expr('{{ Number($json.http_status ?? 0) }}'), type: 'number' },
          { id: 'error-code', name: 'error_code', value: expr('{{ $json.error_code ?? "PYTHON_RESEARCH_ERROR" }}'), type: 'string' },
          {
            id: 'message',
            name: 'message',
            value: expr('{{ $json.error_message ?? "The Python research agent returned an error." }}'),
            type: 'string',
          },
          {
            id: 'errors',
            name: 'errors',
            value: expr('{{ { category: "python", code: ($json.error_code ?? "PYTHON_RESEARCH_ERROR"), message: ($json.error_message ?? "The Python research agent returned an error."), http_status: Number($json.http_status ?? 0) } }}'),
            type: 'object',
          },
        ],
      },
    },
  },
  output: [
    {
      status: 'failed',
      stage: 'research_execution',
      timestamp: '2026-08-01T12:00:00.000Z',
      http_status: 500,
      error_code: 'PYTHON_RESEARCH_ERROR',
      message: 'The Python research agent returned an error.',
      errors: {
        category: 'python',
        code: 'PYTHON_RESEARCH_ERROR',
        message: 'The Python research agent returned an error.',
        http_status: 500,
      },
    },
  ],
});

const timeout = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Timeout',
    position: [2380, 100],
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'status', name: 'status', value: 'failed', type: 'string' },
          { id: 'stage', name: 'stage', value: 'research_execution', type: 'string' },
          { id: 'timestamp', name: 'timestamp', value: expr('{{ $json.timestamp ?? $now.toISO() }}'), type: 'string' },
          { id: 'http-status', name: 'http_status', value: expr('{{ Number($json.http_status ?? 408) }}'), type: 'number' },
          { id: 'error-code', name: 'error_code', value: 'REQUEST_TIMEOUT', type: 'string' },
          {
            id: 'message',
            name: 'message',
            value: 'The Python research agent timed out.',
            type: 'string',
          },
          {
            id: 'errors',
            name: 'errors',
            value: expr('{{ { category: "timeout", code: "REQUEST_TIMEOUT", message: "The Python research agent timed out.", http_status: Number($json.http_status ?? 408) } }}'),
            type: 'object',
          },
        ],
      },
    },
  },
  output: [
    {
      status: 'failed',
      stage: 'research_execution',
      timestamp: '2026-08-01T12:00:00.000Z',
      http_status: 408,
      error_code: 'REQUEST_TIMEOUT',
      message: 'The Python research agent timed out.',
      errors: {
        category: 'timeout',
        code: 'REQUEST_TIMEOUT',
        message: 'The Python research agent timed out.',
        http_status: 408,
      },
    },
  ],
});

const unexpectedError = node({
  type: 'n8n-nodes-base.set',
  version: 3.5,
  config: {
    name: 'Unexpected Error',
    position: [2380, 500],
    parameters: {
      mode: 'manual',
      includeOtherFields: false,
      assignments: {
        assignments: [
          { id: 'status', name: 'status', value: 'failed', type: 'string' },
          { id: 'stage', name: 'stage', value: 'research_execution', type: 'string' },
          { id: 'timestamp', name: 'timestamp', value: expr('{{ $json.timestamp ?? $now.toISO() }}'), type: 'string' },
          { id: 'http-status', name: 'http_status', value: expr('{{ Number($json.http_status ?? 500) }}'), type: 'number' },
          { id: 'error-code', name: 'error_code', value: expr('{{ $json.error_code ?? "UNEXPECTED_RESEARCH_ERROR" }}'), type: 'string' },
          {
            id: 'message',
            name: 'message',
            value: expr('{{ $json.error_message ?? "Unexpected research workflow error." }}'),
            type: 'string',
          },
          {
            id: 'errors',
            name: 'errors',
            value: expr('{{ { category: "unexpected", code: ($json.error_code ?? "UNEXPECTED_RESEARCH_ERROR"), message: ($json.error_message ?? "Unexpected research workflow error."), http_status: Number($json.http_status ?? 500) } }}'),
            type: 'object',
          },
        ],
      },
    },
  },
  output: [
    {
      status: 'failed',
      stage: 'research_execution',
      timestamp: '2026-08-01T12:00:00.000Z',
      http_status: 500,
      error_code: 'UNEXPECTED_RESEARCH_ERROR',
      message: 'Unexpected research workflow error.',
      errors: {
        category: 'unexpected',
        code: 'UNEXPECTED_RESEARCH_ERROR',
        message: 'Unexpected research workflow error.',
        http_status: 500,
      },
    },
  ],
});

const inputNote = sticky('## Input\n\nManual demo and webhook entry points normalize into company, ticker, cik, and query.', [startResearchDemo, prepareDemoRequest, researchApi, normalizeWebhookRequest], { color: 2 });
const validationNote = sticky('## Validation\n\nValidate required research fields early and route invalid requests to a deterministic JSON error.', [validateResearchInput, inputValidAndComplete, validationError], { color: 4 });
const agentNote = sticky('## Research Agent\n\nCall the external Python research service only. SEC, OpenAI, Pinecone, LangGraph, and RAG stay in Python.', [runAutonomousResearchAgent, normalizeAgentResponse, researchSuccessful, timeoutCheck, pythonErrorCheck], { color: 6 });
const outputNote = sticky('## Output\n\nNormalize the Python response into presentation-safe research fields and deterministic error payloads.', [buildResearchSummary, researchResult, pythonError, timeout, unexpectedError], { color: 3 });
const presentationNote = sticky('## Presentation\n\nKeep the demo readable for the Ironhack final project with stable labels, consistent branching, and no crossed connections.', [inputNote, validationNote, agentNote, outputNote], { color: 5 });
const architectureNote = sticky('## Architecture\n\nTwo independent triggers feed one validation chain. Success flows to the summary branch, while validation, Python, timeout, and unexpected branches terminate cleanly.', [startResearchDemo, researchApi, validateResearchInput, runAutonomousResearchAgent, researchResult], { color: 1 });

export default workflow('autonomous-company-research-agent', 'Autonomous Company Research Agent')
  .add(startResearchDemo.to(prepareDemoRequest.to(validateResearchInput)))
  .add(researchApi.to(normalizeWebhookRequest.to(validateResearchInput)))
  .add(validateResearchInput.to(inputValidAndComplete.onTrue(runAutonomousResearchAgent.to(normalizeAgentResponse.to(researchSuccessful.onTrue(buildResearchSummary.to(researchResult)).onFalse(timeoutCheck.onTrue(timeout).onFalse(pythonErrorCheck.onTrue(pythonError).onFalse(unexpectedError)))))).onFalse(validationError)))
  .add(inputNote)
  .add(validationNote)
  .add(agentNote)
  .add(outputNote)
  .add(presentationNote)
  .add(architectureNote);
