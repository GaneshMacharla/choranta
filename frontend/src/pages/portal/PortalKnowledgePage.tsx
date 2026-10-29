import React from 'react';
import { KnowledgeBase } from '../../components/knowledge/KnowledgeBase';
import { portalKnowledge } from '../../services/knowledge';

/** Clients upload documents about their business; Choranta's team builds their AI employees from them. */
export const PortalKnowledgePage: React.FC = () => (
  <div className="mx-auto max-w-5xl space-y-4">
    <div>
      <h1 className="text-xl font-bold">Knowledge</h1>
      <p className="text-xs text-slate-400">
        Upload the documents you already have about your business: brochure, price list, fee chart, prospectus. Our team reads
        them and sets up what your AI employees tell callers.
      </p>
    </div>
    <KnowledgeBase api={portalKnowledge} mode="client" />
  </div>
);
