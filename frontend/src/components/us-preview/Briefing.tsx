'use client';

interface BriefingData {
  timestamp: string;
  content: string;
  citations: string[];
}

export default function Briefing({ data }: { data: BriefingData | null }) {
  if (!data) return <BriefingSkeleton />;

  const { content, citations } = data;

  // Simple markdown-like rendering
  const renderContent = (text: string) => {
    const lines = text.split('\n');
    return lines.map((line, i) => {
      // Headers
      if (line.startsWith('### ')) return <h4 key={i} className="text-base font-bold text-white mt-4 mb-2">{line.slice(4)}</h4>;
      if (line.startsWith('## ')) return <h3 key={i} className="text-lg font-bold text-white mt-4 mb-2">{line.slice(3)}</h3>;
      if (line.startsWith('# ')) return <h2 key={i} className="text-xl font-bold text-white mt-4 mb-2">{line.slice(2)}</h2>;

      // Blockquote
      if (line.startsWith('> ')) return <blockquote key={i} className="border-l-2 border-blue-500/50 pl-3 text-gray-400 italic my-2">{line.slice(2)}</blockquote>;

      // Bold text within line
      const boldParsed = line.replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>');
      // Inline code
      const codeParsed = boldParsed.replace(/`(.*?)`/g, '<code class="px-1.5 py-0.5 rounded bg-gray-800 text-blue-400 text-xs font-mono">$1</code>');

      // Bullet points
      if (line.startsWith('- ') || line.startsWith('* ')) {
        return (
          <div key={i} className="flex gap-2 my-1">
            <span className="text-blue-400 mt-0.5">•</span>
            <span className="text-gray-300 text-sm leading-relaxed" dangerouslySetInnerHTML={{ __html: codeParsed.slice(2) }} />
          </div>
        );
      }

      // Empty line
      if (line.trim() === '') return <div key={i} className="h-2"></div>;

      // Regular paragraph
      return <p key={i} className="text-gray-300 text-sm leading-relaxed my-1" dangerouslySetInnerHTML={{ __html: codeParsed }} />;
    });
  };

  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <i className="fas fa-robot text-indigo-400"></i>
          <h3 className="text-lg font-bold text-white">AI Market Briefing</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/10 border border-indigo-500/30 text-indigo-400">
            Perplexity
          </span>
        </div>
      </div>

      <div className="prose prose-invert max-w-none">
        {renderContent(content)}
      </div>

      {citations && citations.length > 0 && (
        <div className="mt-6 pt-4 border-t border-white/5">
          <div className="text-xs text-gray-500 mb-2">
            <i className="fas fa-link mr-1"></i>Sources
          </div>
          <div className="flex flex-wrap gap-2">
            {citations.map((url, i) => (
              <a
                key={i}
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400/70 hover:text-blue-400 transition-colors bg-blue-500/5 px-2 py-1 rounded border border-blue-500/10"
              >
                [{i + 1}] {new URL(url).hostname.replace('www.', '')}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function BriefingSkeleton() {
  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="w-36 h-5 rounded bg-gray-700 animate-pulse mb-6"></div>
      <div className="space-y-3">
        <div className="w-full h-4 rounded bg-gray-700 animate-pulse"></div>
        <div className="w-5/6 h-4 rounded bg-gray-700 animate-pulse"></div>
        <div className="w-4/6 h-4 rounded bg-gray-700 animate-pulse"></div>
        <div className="w-full h-4 rounded bg-gray-700 animate-pulse mt-4"></div>
        <div className="w-3/4 h-4 rounded bg-gray-700 animate-pulse"></div>
      </div>
    </div>
  );
}
