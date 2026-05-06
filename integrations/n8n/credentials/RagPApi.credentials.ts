import type {
	IAuthenticateGeneric,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class RagPApi implements ICredentialType {
	name = 'ragPApi';

	displayName = 'RAG-Platform API';

	// eslint-disable-next-line n8n-nodes-base/cred-class-field-documentation-url-miscased
	documentationUrl = 'https://lekottt.ru/docs/auth';

	properties: INodeProperties[] = [
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			required: true,
			description:
				'Personal API key. Generate one at https://lekottt.ru/dashboard/api-keys.',
		},
		{
			displayName: 'Base URL',
			name: 'baseUrl',
			type: 'string',
			default: 'https://api.lekottt.ru',
			required: true,
			description:
				'Base URL of the rag-p API. Override only when running self-hosted.',
		},
		{
			displayName: 'Verify SSL',
			name: 'verifySsl',
			type: 'boolean',
			default: true,
			description:
				'Whether to verify TLS certificates. Disable only for development with self-signed certs.',
		},
	];

	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				Authorization: '=Bearer {{$credentials.apiKey}}',
			},
		},
	};

	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{$credentials.baseUrl}}',
			url: '/api/v1/rag/usage/quota',
			method: 'GET',
			skipSslCertificateValidation: '={{ !$credentials.verifySsl }}',
		},
	};
}
