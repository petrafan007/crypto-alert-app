import React from 'react';

export default function PortfolioAuditPolicy({ policy, module = false, guidance }) {
  if (!policy) return <p>Shared audit instructions will appear after the AI configuration is loaded.</p>;
  return <details style={{ marginTop: 12 }}>
    <summary>Shared system instructions applied to this {module ? 'specialist' : 'master'} prompt</summary>
    <p>The editable prompt and shared review guidance are combined with these fixed evidence and paper-safety rules. The configured numeric annual target overrides legacy ranges; custom prompts are preserved.</p>
    {[
      ['Paper research purpose', policy.engine_purpose],
      ...(module ? [['Shared review guidance (edit in Master AI Configuration)', guidance ?? policy.default_guidance]] : []),
      ['Evidence and goal measurement rules', policy.evidence_rules],
      ['Report scope and format', module ? policy.module_scope : policy.master_scope],
    ].map(([label, content]) => <div key={label}><h5>{label}</h5><p style={{ fontSize: 12, whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{content}</p></div>)}
  </details>;
}
