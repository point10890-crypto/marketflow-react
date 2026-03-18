import Link from 'next/link';

export default function TermsPage() {
    return (
        <div className="min-h-screen bg-black p-8">
            <div className="max-w-3xl mx-auto">
                <Link href="/" className="text-gray-500 hover:text-white text-sm mb-8 inline-block">
                    <i className="fas fa-arrow-left mr-2"></i>Back
                </Link>

                <h1 className="text-4xl font-bold text-white tracking-tighter mb-8">Terms of Service</h1>

                <div className="prose prose-invert prose-sm max-w-none space-y-6 text-gray-400">
                    <section>
                        <h2 className="text-xl font-bold text-white">1. Acceptance of Terms</h2>
                        <p>By accessing and using CryptoAnalytics (&quot;the Service&quot;), you agree to be bound by these Terms of Service. If you do not agree, do not use the Service.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">2. Description of Service</h2>
                        <p>CryptoAnalytics provides market analysis tools, data visualization, and AI-generated insights for educational and informational purposes only. The Service is not a registered investment advisor, broker-dealer, or financial planner.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">3. No Investment Advice</h2>
                        <p>All content provided by the Service, including AI-generated recommendations, signals, scores, and analysis, is for informational purposes only and does not constitute investment advice, financial advice, or trading advice. You should consult a qualified financial advisor before making any investment decisions.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">4. User Accounts</h2>
                        <p>You are responsible for maintaining the confidentiality of your account credentials. You agree to notify us immediately of any unauthorized access. We reserve the right to terminate accounts that violate these terms.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">5. Subscription & Billing</h2>
                        <p>Pro subscriptions are billed monthly through Stripe. You may cancel at any time. Refunds are handled on a case-by-case basis. Access to Pro features will continue until the end of the billing period.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">6. Data Accuracy</h2>
                        <p>While we strive for accuracy, market data may be delayed, incomplete, or contain errors. We do not guarantee the accuracy, completeness, or timeliness of any information provided through the Service.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">7. Limitation of Liability</h2>
                        <p>CryptoAnalytics shall not be liable for any direct, indirect, incidental, or consequential damages arising from your use of the Service, including but not limited to financial losses from investment decisions made based on information provided by the Service.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">8. Changes to Terms</h2>
                        <p>We reserve the right to modify these terms at any time. Continued use of the Service constitutes acceptance of the modified terms.</p>
                    </section>
                </div>

                <div className="mt-12 pt-8 border-t border-white/10 text-center text-gray-600 text-xs">
                    <p>Last updated: February 2026</p>
                </div>
            </div>
        </div>
    );
}
