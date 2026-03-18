import Link from 'next/link';

export default function PrivacyPage() {
    return (
        <div className="min-h-screen bg-black p-8">
            <div className="max-w-3xl mx-auto">
                <Link href="/" className="text-gray-500 hover:text-white text-sm mb-8 inline-block">
                    <i className="fas fa-arrow-left mr-2"></i>Back
                </Link>

                <h1 className="text-4xl font-bold text-white tracking-tighter mb-8">Privacy Policy</h1>

                <div className="prose prose-invert prose-sm max-w-none space-y-6 text-gray-400">
                    <section>
                        <h2 className="text-xl font-bold text-white">1. Information We Collect</h2>
                        <p>We collect the following information when you create an account:</p>
                        <ul className="list-disc pl-5 space-y-1">
                            <li>Email address</li>
                            <li>Display name</li>
                            <li>Hashed password (we never store plain text passwords)</li>
                            <li>Subscription tier and billing information (managed by Stripe)</li>
                        </ul>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">2. How We Use Your Information</h2>
                        <p>Your information is used to:</p>
                        <ul className="list-disc pl-5 space-y-1">
                            <li>Authenticate your account</li>
                            <li>Manage your subscription</li>
                            <li>Improve the Service</li>
                        </ul>
                        <p>We do not sell, share, or rent your personal information to third parties.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">3. Data Storage</h2>
                        <p>Your data is stored securely using industry-standard encryption. Passwords are hashed using bcrypt. Payment information is handled entirely by Stripe and never touches our servers.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">4. Cookies</h2>
                        <p>We use session cookies for authentication. No third-party tracking cookies are used.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">5. Data Deletion</h2>
                        <p>You may request deletion of your account and associated data at any time by contacting us. We will process deletion requests within 30 days.</p>
                    </section>

                    <section>
                        <h2 className="text-xl font-bold text-white">6. Changes</h2>
                        <p>We may update this Privacy Policy from time to time. We will notify users of significant changes via email or in-app notification.</p>
                    </section>
                </div>

                <div className="mt-12 pt-8 border-t border-white/10 text-center text-gray-600 text-xs">
                    <p>Last updated: February 2026</p>
                </div>
            </div>
        </div>
    );
}
