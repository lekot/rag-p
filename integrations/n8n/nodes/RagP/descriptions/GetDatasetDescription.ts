import type { INodeProperties } from 'n8n-workflow';

export const getDatasetOperationFields: INodeProperties[] = [
	{
		displayName: 'Dataset ID',
		name: 'datasetId',
		type: 'string',
		default: '',
		required: true,
		placeholder: 'ds_01HXXXX...',
		description: 'ID of the dataset to fetch',
		displayOptions: {
			show: {
				resource: ['dataset'],
				operation: ['getDataset'],
			},
		},
	},
];
