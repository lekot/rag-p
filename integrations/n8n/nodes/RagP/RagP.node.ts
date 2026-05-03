import type {
	IExecuteFunctions,
	IDataObject,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
} from 'n8n-workflow';
import { NodeConnectionTypes, NodeOperationError } from 'n8n-workflow';

import { ragPApiRequest } from './GenericFunctions';
import { queryOperationFields } from './descriptions/QueryDescription';
import { uploadOperationFields } from './descriptions/UploadDescription';
import { getDatasetOperationFields } from './descriptions/GetDatasetDescription';

export class RagP implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'RAG-Platform',
		name: 'ragP',
		icon: 'file:RagP.svg',
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["operation"] + ": " + $parameter["resource"]}}',
		description: 'Interact with the rag-p (RAG-Platform) API',
		defaults: {
			name: 'RAG-Platform',
		},
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		credentials: [
			{
				name: 'ragPApi',
				required: true,
			},
		],
		properties: [
			{
				displayName: 'Resource',
				name: 'resource',
				type: 'options',
				noDataExpression: true,
				options: [
					{
						name: 'Dataset',
						value: 'dataset',
					},
				],
				default: 'dataset',
			},
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				displayOptions: {
					show: {
						resource: ['dataset'],
					},
				},
				options: [
					{
						name: 'Query',
						value: 'query',
						description: 'Run a RAG query against a dataset',
						action: 'Query a dataset',
					},
					{
						name: 'Upload Document',
						value: 'uploadDocument',
						description: 'Upload a text or binary document into a dataset',
						action: 'Upload a document',
					},
					{
						name: 'Get Dataset',
						value: 'getDataset',
						description: 'Fetch dataset metadata and indexing status',
						action: 'Get a dataset',
					},
					{
						name: 'Get Usage Quota',
						value: 'getUsage',
						description: 'Get remaining query quota and plan info',
						action: 'Get usage quota',
					},
				],
				default: 'query',
			},
			...queryOperationFields,
			...uploadOperationFields,
			...getDatasetOperationFields,
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];

		for (let i = 0; i < items.length; i++) {
			try {
				const resource = this.getNodeParameter('resource', i) as string;
				const operation = this.getNodeParameter('operation', i) as string;

				if (resource !== 'dataset') {
					throw new NodeOperationError(
						this.getNode(),
						`Unsupported resource "${resource}"`,
						{ itemIndex: i },
					);
				}

				let response: IDataObject = {};

				if (operation === 'query') {
					const datasetId = this.getNodeParameter('datasetId', i) as string;
					const query = this.getNodeParameter('query', i) as string;
					const topK = this.getNodeParameter('topK', i, 5) as number;
					const additionalOptions = this.getNodeParameter(
						'additionalOptions',
						i,
						{},
					) as IDataObject;

					const body: IDataObject = {
						dataset_id: datasetId,
						query,
						top_k: topK,
					};

					if (additionalOptions.plugin) {
						body.plugin = additionalOptions.plugin;
					}
					if (additionalOptions.filters) {
						const raw = additionalOptions.filters;
						body.filters =
							typeof raw === 'string' ? (JSON.parse(raw) as IDataObject) : (raw as IDataObject);
					}

					response = await ragPApiRequest.call(
						this,
						'POST',
						'/api/v1/rag/query',
						body,
						{},
						{ itemIndex: i },
					);
				} else if (operation === 'uploadDocument') {
					const datasetId = this.getNodeParameter('datasetId', i) as string;
					const inputType = this.getNodeParameter('inputType', i, 'text') as
						| 'text'
						| 'binary';
					const filename = this.getNodeParameter('filename', i, '') as string;

					let fileBuffer: Buffer;
					let resolvedFilename = filename;
					let mimeType = 'text/plain';

					if (inputType === 'binary') {
						const binaryPropertyName = this.getNodeParameter(
							'binaryPropertyName',
							i,
							'data',
						) as string;
						const binaryData = this.helpers.assertBinaryData(i, binaryPropertyName);
						fileBuffer = await this.helpers.getBinaryDataBuffer(i, binaryPropertyName);
						resolvedFilename = filename || binaryData.fileName || 'document.bin';
						mimeType = binaryData.mimeType || 'application/octet-stream';
					} else {
						const textContent = this.getNodeParameter('textContent', i, '') as string;
						fileBuffer = Buffer.from(textContent, 'utf-8');
						resolvedFilename = filename || 'document.txt';
						mimeType = 'text/plain';
					}

					const formData = {
						file: {
							value: fileBuffer,
							options: {
								filename: resolvedFilename,
								contentType: mimeType,
							},
						},
					};

					response = await ragPApiRequest.call(
						this,
						'POST',
						`/api/v1/datasets/${encodeURIComponent(datasetId)}/documents`,
						undefined,
						{},
						{
							itemIndex: i,
							json: false,
							body: formData as unknown as IDataObject,
							headers: {
								// let the HTTP client set the multipart boundary
								'Content-Type': undefined as unknown as string,
							},
						},
					);

					if (typeof response === 'string') {
						try {
							response = JSON.parse(response) as IDataObject;
						} catch {
							response = { raw: response } as IDataObject;
						}
					}
				} else if (operation === 'getDataset') {
					const datasetId = this.getNodeParameter('datasetId', i) as string;
					response = await ragPApiRequest.call(
						this,
						'GET',
						`/api/v1/datasets/${encodeURIComponent(datasetId)}`,
						undefined,
						{},
						{ itemIndex: i },
					);
				} else if (operation === 'getUsage') {
					response = await ragPApiRequest.call(
						this,
						'GET',
						'/api/v1/rag/usage/quota',
						undefined,
						{},
						{ itemIndex: i },
					);
				} else {
					throw new NodeOperationError(
						this.getNode(),
						`Unsupported operation "${operation}"`,
						{ itemIndex: i },
					);
				}

				returnData.push({
					json: response,
					pairedItem: { item: i },
				});
			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({
						json: { error: (error as Error).message },
						pairedItem: { item: i },
					});
					continue;
				}
				throw error;
			}
		}

		return [returnData];
	}
}
