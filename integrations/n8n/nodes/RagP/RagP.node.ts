import type {
	IExecuteFunctions,
	IDataObject,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
} from 'n8n-workflow';
import { NodeConnectionType, NodeOperationError } from 'n8n-workflow';

import { ragPApiRequest } from './GenericFunctions';
import { queryOperationFields } from './descriptions/QueryDescription';

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
		inputs: [NodeConnectionType.Main],
		outputs: [NodeConnectionType.Main],
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
				],
				default: 'query',
			},
			...queryOperationFields,
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

					response = await ragPApiRequest.call(this, 'POST', '/api/v1/rag/query', body);
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
