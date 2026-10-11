import React, { useEffect, useState } from 'react';
import { BookOpen, RefreshCw, FileText, CheckCircle2, Database, Sparkles } from 'lucide-react';
import { catalogsService } from '../services/catalogs';
import { KnowledgeSource } from '../types';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';

export const KnowledgePage: React.FC = () => {
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchKnowledge = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await catalogsService.listKnowledge();
      setSources(data);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch knowledge catalog');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchKnowledge();
  }, []);

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#102d38]">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#00df8f]/15 border border-[#00df8f]/30 text-[#00df8f]">
              <BookOpen className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-slate-100">Knowledge Base &amp; Grounding</h1>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Enterprise knowledge catalogs, policy documents, and retrieval grounding for voice employees.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" onClick={fetchKnowledge} className="gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh Catalog
          </Button>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="p-4 border-l-4 border-l-[#00df8f]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Knowledge Catalogs</span>
          <div className="text-2xl font-bold font-mono text-slate-100 mt-1">{sources.length}</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Active reference documents in database</span>
        </Card>
        <Card className="p-4 border-l-4 border-l-[#22d3ee]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Grounding Format</span>
          <div className="text-2xl font-bold font-mono text-[#22d3ee] mt-1">Structured RAG</div>
          <span className="text-[11px] text-slate-500 mt-1 block">System prompt injection &amp; retrieval indexing</span>
        </Card>
        <Card className="p-4 border-l-4 border-l-[#00df8f]">
          <span className="text-xs text-slate-400 uppercase tracking-wider text-[11px]">Grounding Latency</span>
          <div className="text-2xl font-bold font-mono text-[#00df8f] mt-1">&lt; 15 ms</div>
          <span className="text-[11px] text-slate-500 mt-1 block">Zero-cold-start in-memory context resolution</span>
        </Card>
      </div>

      {/* Knowledge Sources Grid */}
      <Card
        title={`Reference Knowledge Catalogs (${sources.length})`}
        subtitle="Knowledge sources attached to AI employees provide factual domain accuracy during calls"
      >
        {isLoading ? (
          <LoadingState message="Loading knowledge sources..." />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchKnowledge} />
        ) : sources.length === 0 ? (
          <EmptyState
            icon={<BookOpen className="h-6 w-6" />}
            title="No knowledge sources found."
            description="Knowledge documents can be seeded or attached to client voice employees."
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {sources.map((item) => (
              <div
                key={item.id}
                className="rounded-lg border border-[#143c49] bg-[#06141a] p-4 flex flex-col justify-between hover:border-[#00df8f]/40 transition-colors"
              >
                <div>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2.5">
                      <FileText className="h-4 w-4 text-[#00df8f] shrink-0" />
                      <div>
                        <h3 className="text-sm font-semibold text-slate-100">{item.name}</h3>
                        <span className="text-[11px] font-mono text-slate-500">{item.id}</span>
                      </div>
                    </div>
                    <Badge variant="green" dot size="sm">
                      {item.status}
                    </Badge>
                  </div>

                  <p className="text-xs text-slate-300 mt-3 leading-relaxed">
                    {item.description || 'Enterprise reference document for client interaction guidance.'}
                  </p>
                </div>

                <div className="mt-4 pt-3 border-t border-[#102d38] flex items-center justify-between text-[11px] text-slate-400">
                  <span className="font-mono text-slate-400">
                    Type: <span className="text-slate-200">{item.type}</span>
                  </span>
                  <span className="text-slate-500 font-mono text-[10px]">
                    {new Date(item.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
};
