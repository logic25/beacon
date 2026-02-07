import React from 'react';

const ArchitectureDiagram = () => {
  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <h1 className="text-2xl font-bold text-center mb-8">Greenlight AI Platform Architecture</h1>

      {/* User Touchpoints */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-600 mb-4">User Touchpoints</h2>
        <div className="flex justify-around gap-4">
          {/* Google Chat */}
          <div className="bg-white rounded-lg shadow-md p-4 w-48 text-center border-2 border-green-500">
            <div className="text-3xl mb-2">💬</div>
            <div className="font-semibold">Google Chat</div>
            <div className="text-sm text-gray-500">Internal Team</div>
            <div className="text-xs text-green-600 mt-2">✅ BUILT</div>
          </div>

          {/* iPhone App */}
          <div className="bg-white rounded-lg shadow-md p-4 w-48 text-center border-2 border-yellow-500">
            <div className="text-3xl mb-2">📱</div>
            <div className="font-semibold">iPhone App</div>
            <div className="text-sm text-gray-500">Field Zoning Tool</div>
            <div className="text-xs text-yellow-600 mt-2">🔜 PLANNED</div>
          </div>

          {/* Website Bot */}
          <div className="bg-white rounded-lg shadow-md p-4 w-48 text-center border-2 border-yellow-500">
            <div className="text-3xl mb-2">🌐</div>
            <div className="font-semibold">Website Bot</div>
            <div className="text-sm text-gray-500">Lead Capture</div>
            <div className="text-xs text-yellow-600 mt-2">🔜 PLANNED</div>
          </div>

          {/* Ordino */}
          <div className="bg-white rounded-lg shadow-md p-4 w-48 text-center border-2 border-blue-500">
            <div className="text-3xl mb-2">📋</div>
            <div className="font-semibold">Ordino CRM</div>
            <div className="text-sm text-gray-500">Project Management</div>
            <div className="text-xs text-blue-600 mt-2">🔗 INTEGRATE</div>
          </div>
        </div>
      </div>

      {/* Arrow down */}
      <div className="text-center text-3xl text-gray-400 mb-4">↓</div>

      {/* API Layer */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-600 mb-4">API Layer (Your Server)</h2>
        <div className="bg-gradient-to-r from-purple-500 to-indigo-600 rounded-lg shadow-lg p-6 text-white">
          <div className="flex justify-around">
            <div className="text-center">
              <div className="font-semibold">/chat</div>
              <div className="text-sm opacity-80">Q&A endpoint</div>
            </div>
            <div className="text-center">
              <div className="font-semibold">/lookup</div>
              <div className="text-sm opacity-80">Property data</div>
            </div>
            <div className="text-center">
              <div className="font-semibold">/zoning</div>
              <div className="text-sm opacity-80">Zoning analysis</div>
            </div>
            <div className="text-center">
              <div className="font-semibold">/analytics</div>
              <div className="text-sm opacity-80">Usage stats</div>
            </div>
            <div className="text-center">
              <div className="font-semibold">/ordino</div>
              <div className="text-sm opacity-80">CRM sync</div>
            </div>
          </div>
        </div>
      </div>

      {/* Arrow down */}
      <div className="text-center text-3xl text-gray-400 mb-4">↓</div>

      {/* Core Services */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-600 mb-4">Core Services</h2>
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-white rounded-lg shadow p-4 border-l-4 border-green-500">
            <div className="font-semibold text-green-700">Claude (Haiku)</div>
            <div className="text-sm text-gray-500">LLM responses</div>
            <div className="text-xs text-green-600 mt-1">✅ Built</div>
          </div>
          <div className="bg-white rounded-lg shadow p-4 border-l-4 border-green-500">
            <div className="font-semibold text-green-700">RAG / Pinecone</div>
            <div className="text-sm text-gray-500">Your documents</div>
            <div className="text-xs text-green-600 mt-1">✅ Built</div>
          </div>
          <div className="bg-white rounded-lg shadow p-4 border-l-4 border-green-500">
            <div className="font-semibold text-green-700">NYC Open Data</div>
            <div className="text-sm text-gray-500">Live property info</div>
            <div className="text-xs text-green-600 mt-1">✅ Built</div>
          </div>
          <div className="bg-white rounded-lg shadow p-4 border-l-4 border-yellow-500">
            <div className="font-semibold text-yellow-700">Analytics DB</div>
            <div className="text-sm text-gray-500">Usage tracking</div>
            <div className="text-xs text-yellow-600 mt-1">🔜 Next</div>
          </div>
        </div>
      </div>

      {/* Arrow down */}
      <div className="text-center text-3xl text-gray-400 mb-4">↓</div>

      {/* Data Sources */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-600 mb-4">Knowledge Sources</h2>
        <div className="flex justify-around gap-4">
          <div className="bg-gray-100 rounded-lg p-4 w-40 text-center">
            <div className="text-2xl mb-1">📄</div>
            <div className="text-sm font-medium">Your PDFs</div>
            <div className="text-xs text-gray-500">Determinations</div>
          </div>
          <div className="bg-gray-100 rounded-lg p-4 w-40 text-center">
            <div className="text-2xl mb-1">💡</div>
            <div className="text-sm font-medium">Team Tips</div>
            <div className="text-xs text-gray-500">/correct /tip</div>
          </div>
          <div className="bg-yellow-100 rounded-lg p-4 w-40 text-center border border-yellow-300">
            <div className="text-2xl mb-1">📖</div>
            <div className="text-sm font-medium">Zoning Res</div>
            <div className="text-xs text-gray-500">~2000 pages</div>
          </div>
          <div className="bg-gray-100 rounded-lg p-4 w-40 text-center">
            <div className="text-2xl mb-1">🏛️</div>
            <div className="text-sm font-medium">DOB Bulletins</div>
            <div className="text-xs text-gray-500">Service notices</div>
          </div>
          <div className="bg-gray-100 rounded-lg p-4 w-40 text-center">
            <div className="text-2xl mb-1">🌐</div>
            <div className="text-sm font-medium">NYC Open Data</div>
            <div className="text-xs text-gray-500">Live API</div>
          </div>
        </div>
      </div>

      {/* Dashboard Preview */}
      <div className="mt-12 border-t pt-8">
        <h2 className="text-lg font-semibold text-gray-600 mb-4">Analytics Dashboard (Simple)</h2>
        <div className="bg-white rounded-lg shadow-lg p-6">
          <div className="grid grid-cols-4 gap-6 mb-6">
            <div className="text-center">
              <div className="text-3xl font-bold text-blue-600">247</div>
              <div className="text-sm text-gray-500">Questions This Week</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold text-green-600">89%</div>
              <div className="text-sm text-gray-500">Answered by Bot</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold text-purple-600">34</div>
              <div className="text-sm text-gray-500">Corrections Captured</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold text-orange-600">12</div>
              <div className="text-sm text-gray-500">Escalated to Human</div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-6">
            <div>
              <h3 className="font-medium mb-2">Top Questions</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between bg-gray-50 p-2 rounded">
                  <span>Zoning use group questions</span>
                  <span className="text-gray-500">45</span>
                </div>
                <div className="flex justify-between bg-gray-50 p-2 rounded">
                  <span>DOB filing process</span>
                  <span className="text-gray-500">38</span>
                </div>
                <div className="flex justify-between bg-gray-50 p-2 rounded">
                  <span>Property lookups</span>
                  <span className="text-gray-500">32</span>
                </div>
              </div>
            </div>
            <div>
              <h3 className="font-medium mb-2">Needs Review</h3>
              <div className="space-y-2 text-sm">
                <div className="bg-red-50 p-2 rounded text-red-700">
                  "What's the new LL97 threshold?" - Low confidence
                </div>
                <div className="bg-red-50 p-2 rounded text-red-700">
                  "Can I combine lots in R7A?" - Site specific
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Monetization Flow */}
      <div className="mt-8 border-t pt-8">
        <h2 className="text-lg font-semibold text-gray-600 mb-4">Website Bot → Paid Consultation Flow</h2>
        <div className="flex items-center justify-center gap-4">
          <div className="bg-blue-100 rounded-lg p-4 text-center w-40">
            <div className="text-2xl mb-1">👋</div>
            <div className="text-sm font-medium">Visitor asks question</div>
          </div>
          <div className="text-2xl">→</div>
          <div className="bg-green-100 rounded-lg p-4 text-center w-40">
            <div className="text-2xl mb-1">🤖</div>
            <div className="text-sm font-medium">Bot answers basics</div>
          </div>
          <div className="text-2xl">→</div>
          <div className="bg-yellow-100 rounded-lg p-4 text-center w-40">
            <div className="text-2xl mb-1">🤔</div>
            <div className="text-sm font-medium">Complex question?</div>
          </div>
          <div className="text-2xl">→</div>
          <div className="bg-purple-100 rounded-lg p-4 text-center w-40">
            <div className="text-2xl mb-1">📅</div>
            <div className="text-sm font-medium">Schedule + Pay</div>
          </div>
          <div className="text-2xl">→</div>
          <div className="bg-green-500 text-white rounded-lg p-4 text-center w-40">
            <div className="text-2xl mb-1">💰</div>
            <div className="text-sm font-medium">Paid Consultation</div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ArchitectureDiagram;
