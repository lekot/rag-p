import type {
	IExecuteFunctions,
	IDataObject,
	IHttpRequestMethods,
	IHttpRequestOptions,
	JsonObject,
} from 'n8n-workflow';
import { NodeApiError, NodeOperationError } from 'n8n-workflow';

interface RagPRequestExtras extends Partial<IHttpRequestOptions> {
	itemIndex?: number;
}

/**
 * Wrapper around `httpRequestWithAuthentication` that maps API errors onto
 * n8n's error model:
 *
 *  - 4xx           => NodeOperationError  (client error, not retryable)
 *  - 5xx / network => NodeApiError        (retryable per n8n's policy)
 */
export async function ragPApiRequest(
	this: IExecuteFunctions,
	method: IHttpRequestMethods,
	resource: string,
	body: IDataObject | Buffer | undefined = undefined,
	qs: IDataObject = {},
	options: RagPRequestExtras = {},
): Promise<IDataObject> {
	const credentials = await this.getCredentials('ragPApi');
	const baseUrl = ((credentials.baseUrl as string) || 'https://api.lekottt.ru').replace(
		/\/$/,
		'',
	);
	const verifySsl = credentials.verifySsl !== false;
	const { itemIndex = 0, ...httpOverrides } = options;

	const requestOptions: IHttpRequestOptions = {
		method,
		url: `${baseUrl}${resource}`,
		qs,
		json: true,
		skipSslCertificateValidation: !verifySsl,
		...httpOverrides,
	};

	if (body !== undefined) {
		requestOptions.body = body as IDataObject;
	}

	try {
		const response = (await this.helpers.httpRequestWithAuthentication.call(
			this,
			'ragPApi',
			requestOptions,
		)) as IDataObject;
		return response;
	} catch (error) {
		const status = (error as { statusCode?: number; httpCode?: number }).statusCode
			?? (error as { httpCode?: number }).httpCode;

		if (typeof status === 'number' && status >= 400 && status < 500) {
			throw new NodeOperationError(this.getNode(), error as Error, {
				itemIndex,
				description: `RAG-Platform returned HTTP ${status}. Check parameters and credentials.`,
			});
		}
		throw new NodeApiError(this.getNode(), error as JsonObject);
	}
}
