import Link from 'next/link';

export default function DisclaimerPage() {
    return (
        <div className="min-h-screen bg-black p-8">
            <div className="max-w-3xl mx-auto">
                <Link href="/" className="text-gray-500 hover:text-white text-sm mb-8 inline-block">
                    <i className="fas fa-arrow-left mr-2"></i>Back
                </Link>

                <h1 className="text-4xl font-bold text-white tracking-tighter mb-8">Investment Disclaimer</h1>

                <div className="p-6 rounded-2xl bg-yellow-500/5 border border-yellow-500/20 mb-8">
                    <div className="flex items-start gap-3">
                        <i className="fas fa-exclamation-triangle text-yellow-500 text-xl mt-1"></i>
                        <div>
                            <h2 className="text-lg font-bold text-yellow-400 mb-2">Important Warning</h2>
                            <p className="text-yellow-400/80 text-sm leading-relaxed">
                                CryptoAnalytics is an educational tool. All signals, scores, recommendations, and AI-generated content are for informational and educational purposes only. This is NOT financial advice. Past performance does NOT guarantee future results. You could lose money by following any information presented on this platform.
                            </p>
                        </div>
                    </div>
                </div>

                <div className="prose prose-invert prose-sm max-w-none space-y-6 text-gray-400">
                    <section>
                        <h2 className="text-xl font-bold text-white">No Investment Advice</h2>
                        <p>The information provided by CryptoAnalytics does not constitute investment advice, financial advice, trading advice, or any other sort of advice. You should not treat any of the content as such. CryptoAnalytics does not recommend that any financial instrument should be bought, sold, or held by you. Nothing on this platform should be construed as an offer, recommendation, or solicitation to buy or sell any security or financial product.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">AI-Generated Content</h2>
                        <p>This platform uses artificial intelligence and machine learning models to generate analysis, predictions, and recommendations. AI models can be wrong. They may produce inaccurate, misleading, or incomplete information. AI-generated content should never be the sole basis for investment decisions.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">Market Risk</h2>
                        <p>All investments involve risk, including the possible loss of principal. The value of investments can go down as well as up. Past performance of any strategy, algorithm, or investment does not guarantee future results. Market conditions can change rapidly and without warning.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">Data Accuracy</h2>
                        <p>Market data displayed on this platform may be delayed, inaccurate, or incomplete. We source data from third-party providers and cannot guarantee its accuracy. Always verify data with your broker or official market sources before making investment decisions.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">Backtesting Limitations</h2>
                        <p>Backtested results shown on this platform are hypothetical and do not represent actual trading results. Backtesting has inherent limitations including hindsight bias, survivorship bias, and the inability to account for all market conditions. Actual trading results may differ significantly.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">Your Responsibility</h2>
                        <p>You are solely responsible for your own investment decisions. Before making any investment, you should:</p>
                        <ul className="list-disc pl-5 space-y-1">
                            <li>Conduct your own due diligence</li>
                            <li>Consult with a qualified, licensed financial advisor</li>
                            <li>Consider your own financial situation and risk tolerance</li>
                            <li>Never invest money you cannot afford to lose</li>
                        </ul>
                    </section>
                </div>

                <div className="mt-12 pt-8 border-t border-white/10 text-center text-gray-600 text-xs">
                    <p>Last updated: February 2026</p>
                </div>
            </div>
        </div>
    );
}
