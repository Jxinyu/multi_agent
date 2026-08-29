import { ChevronDown, FileText, Search, SlidersHorizontal, X } from 'lucide-react';
import { FormEvent, useMemo, useState } from 'react';

import { searchKnowledge } from '../../api/user';
import type { SearchEvidence, SearchMode } from '../../types';

const modeLabels: Record<SearchMode, string> = { milvus: '向量', graph: '图谱', mg: '混合' };

export function EnterpriseSearchPage() {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchMode>('mg');
  const [items, setItems] = useState<SearchEvidence[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selected = useMemo(() => items.find((item) => item.id === selectedId) ?? items[0] ?? null, [items, selectedId]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const normalized = query.trim();
    if (!normalized || busy) return;
    setBusy(true);
    setError('');
    try {
      const result = await searchKnowledge(normalized, mode);
      setItems(result.items);
      setElapsedMs(result.elapsed_ms);
      setSelectedId(result.items[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '检索失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ru-search-page">
      <form className="ru-search-command" onSubmit={submit}>
        <div className="ru-search-box">
          <Search size={18} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索制度、合同条款或业务流程" aria-label="企业搜索关键词" />
          {query ? <button type="button" onClick={() => setQuery('')} aria-label="清空关键词"><X size={16} /></button> : null}
          <button className="ru-primary-command" type="submit" disabled={!query.trim() || busy}>{busy ? '检索中' : '搜索'}</button>
        </div>
        <div className="ru-search-filters">
          <SlidersHorizontal size={15} />
          <span>检索方式</span>
          {Object.entries(modeLabels).map(([value, label]) => (
            <button key={value} type="button" className={mode === value ? 'is-active' : ''} onClick={() => setMode(value as SearchMode)}>{label}</button>
          ))}
        </div>
      </form>

      <div className="ru-search-workspace">
        <aside className="ru-search-refine">
          <header><strong>精炼搜索</strong><button type="button">重置</button></header>
          <fieldset>
            <legend>来源类型</legend>
            <label><input type="checkbox" defaultChecked /> 制度与流程</label>
            <label><input type="checkbox" defaultChecked /> 合同与法务</label>
            <label><input type="checkbox" defaultChecked /> 技术文档</label>
          </fieldset>
          <fieldset>
            <legend>权限范围</legend>
            <label><input type="checkbox" defaultChecked /> 我可访问</label>
            <label><input type="checkbox" /> 仅我所有</label>
          </fieldset>
          <div className="ru-search-diagnostic">
            <span>查询诊断</span>
            <strong>{elapsedMs === null ? '尚未执行' : `${elapsedMs} ms`}</strong>
            <small>{modeLabels[mode]}检索</small>
          </div>
        </aside>

        <section className="ru-search-results">
          <header><span>共找到 <strong>{items.length}</strong> 条证据</span><button type="button">综合相关度 <ChevronDown size={14} /></button></header>
          {error ? <div className="ru-inline-error">{error}</div> : null}
          {!busy && !error && items.length === 0 ? <div className="ru-data-empty"><Search size={30} /><strong>输入关键词开始检索</strong><span>结果仅包含当前账号有权访问的证据。</span></div> : null}
          <div className="ru-result-list">
            {items.map((item, index) => (
              <button key={item.id} type="button" className={selected?.id === item.id ? 'is-selected' : ''} onClick={() => setSelectedId(item.id)}>
                <div className="ru-result-score">{item.score === null ? '--' : item.score.toFixed(2)}</div>
                <div className="ru-result-copy">
                  <span><em>{modeLabels[mode]}</em><i>{item.kind}</i><b>[{index + 1}]</b></span>
                  <strong><FileText size={15} /> {item.source}</strong>
                  <p>{item.content}</p>
                  <small>后端：{item.backend || modeLabels[mode]} · 权限：当前账号可见</small>
                </div>
              </button>
            ))}
          </div>
        </section>

        <aside className="ru-reader-panel">
          {selected ? (
            <>
              <header><FileText size={18} /><strong>{selected.source}</strong></header>
              <div className="ru-reader-tabs"><button className="is-active" type="button">证据定位</button><button type="button">文档导航</button></div>
              <article><span>命中片段</span><p>{selected.content}</p></article>
              <dl><div><dt>证据类型</dt><dd>{selected.kind}</dd></div><div><dt>匹配分值</dt><dd>{selected.score?.toFixed(4) ?? 'N/A'}</dd></div><div><dt>检索后端</dt><dd>{selected.backend || modeLabels[mode]}</dd></div></dl>
            </>
          ) : <div className="ru-data-empty"><FileText size={30} /><strong>未选择证据</strong><span>执行检索后可在此阅读命中原文。</span></div>}
        </aside>
      </div>
    </div>
  );
}
